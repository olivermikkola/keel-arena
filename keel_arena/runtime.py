"""Bounded OpenAI-compatible execution wrapper, uploaded into a Harbor sandbox.

Standalone standard-library module. No provider calls happen until explicitly run.
The upstream transport is nonstreaming; Keel receives a compatible SSE envelope.
"""

import argparse
import hashlib
import json
import os
import signal
import subprocess
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

LIMIT = 4 * 1024 * 1024


def read_json(source):
    raw = source.read(LIMIT + 1)
    if len(raw) > LIMIT:
        raise ValueError('JSON exceeds runtime limit')
    return json.loads(raw)


def validate_config(config):
    expected = {'binary', 'binary_sha256', 'root', 'home', 'logs', 'model', 'base_url',
                'context_tokens', 'max_model_requests', 'max_output_tokens',
                'temperature', 'top_p', 'seed', 'thinking', 'timeout_seconds'}
    if not isinstance(config, dict) or set(config) != expected:
        raise ValueError('invalid runtime config fields')
    for key in ('context_tokens', 'max_model_requests', 'max_output_tokens', 'timeout_seconds'):
        if type(config[key]) is not int or not 1 <= config[key] <= 1_000_000:
            raise ValueError('invalid runtime budget')
    for key in ('binary', 'root', 'home', 'logs'):
        if not isinstance(config[key], str) or not Path(config[key]).is_absolute():
            raise ValueError('runtime paths must be absolute')
    if not isinstance(config['base_url'], str):
        raise ValueError('provider URL must be a string')
    url = urllib.parse.urlsplit(config['base_url'])
    if url.scheme not in ('http', 'https') or not url.hostname or url.username or url.password or url.query or url.fragment:
        raise ValueError('invalid provider URL')
    if not isinstance(config['model'], str) or not config['model']:
        raise ValueError('model required')
    if config['thinking'] is not None and type(config['thinking']) is not bool:
        raise ValueError('invalid thinking policy')
    if type(config['seed']) is not int:
        raise ValueError('invalid sampling policy')
    if type(config['temperature']) not in (int, float) or not 0 <= config['temperature'] <= 2:
        raise ValueError('invalid temperature')
    if type(config['top_p']) not in (int, float) or not 0 < config['top_p'] <= 1:
        raise ValueError('invalid top_p')
    if not isinstance(config['binary_sha256'], str) or len(config['binary_sha256']) != 64:
        raise ValueError('binary hash required')
    return config


def run(config):
    validate_config(config)
    binary = Path(config['binary'])
    if binary.is_symlink() or not binary.is_file():
        raise ValueError('binary must be a regular file')
    with binary.open('rb') as source:
        if hashlib.file_digest(source, 'sha256').hexdigest() != config['binary_sha256']:
            raise ValueError('binary digest mismatch')
    logs = Path(config['logs'])
    logs.mkdir(parents=True, exist_ok=False, mode=0o700)
    home = Path(config['home'])
    home.mkdir(parents=True, exist_ok=False, mode=0o700)
    state = {'requests': 0, 'responses': 0, 'input_tokens': 0, 'output_tokens': 0,
             'usage_complete': True, 'failure': None}
    lock = threading.Lock()
    deadline = time.monotonic() + config['timeout_seconds']
    api_key = os.environ.get('KEEL_API_KEY')
    instruction = os.environ.get('ARENA_INSTRUCTION')
    if instruction is None:
        raise ValueError('instruction required')

    class Gateway(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass  # Never put provider URLs, prompts or credentials in host logs.

        def respond(self, status, payload, event=False):
            self.send_response(status)
            self.send_header('Content-Type', 'text/event-stream' if event else 'application/json')
            self.send_header('Content-Length', str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def do_POST(self):
            index = None
            try:
                if self.path != '/v1/chat/completions':
                    self.respond(404, b'{}')
                    return
                size = int(self.headers.get('Content-Length', '-1'))
                if not 0 <= size <= LIMIT:
                    raise ValueError('request too large')
                body = json.loads(self.rfile.read(size))
                if not isinstance(body, dict) or not isinstance(body.get('messages'), list):
                    raise ValueError('invalid request')
                with lock:
                    if state['requests'] >= config['max_model_requests']:
                        state['failure'] = 'budget_exhausted'
                        self.respond(429, b'{"error":{"message":"arena request budget exhausted"}}')
                        return
                    state['requests'] += 1
                    index = state['requests']
                body.update(model=config['model'], stream=False,
                            max_tokens=config['max_output_tokens'],
                            temperature=config['temperature'], top_p=config['top_p'], seed=config['seed'])
                body.pop('chat_template_kwargs', None)
                if config['thinking'] is not None:
                    body['chat_template_kwargs'] = {'enable_thinking': config['thinking']}
                body.pop('max_completion_tokens', None)
                body.pop('stream_options', None)
                (logs / f'request-{index}.json').write_text(json.dumps(body) + '\n')
                headers = {'Content-Type': 'application/json'}
                if api_key:
                    headers['Authorization'] = 'Bearer ' + api_key
                request = urllib.request.Request(config['base_url'].rstrip('/') + '/chat/completions',
                                                 data=json.dumps(body).encode(), headers=headers)
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError('deadline exhausted')
                with urllib.request.urlopen(request, timeout=remaining) as response:
                    answer = read_json(response)
                if not isinstance(answer, dict) or not isinstance(answer.get('choices'), list) or len(answer['choices']) != 1:
                    raise ValueError('invalid completion envelope')
                # Evidence is private sandbox output, never printed or uploaded.
                (logs / f'completion-{index}.json').write_text(json.dumps({'request': body, 'response': answer}) + '\n')
                usage = answer.get('usage') or {}
                if not isinstance(usage, dict):
                    raise ValueError('invalid usage')
                if type(usage.get('completion_tokens')) is int and usage['completion_tokens'] > config['max_output_tokens']:
                    raise ValueError('provider violated output budget')
                with lock:
                    for source, target in (('prompt_tokens', 'input_tokens'), ('completion_tokens', 'output_tokens')):
                        value = usage.get(source)
                        if type(value) is int and value >= 0:
                            state[target] += value
                        else:
                            state['usage_complete'] = False
                choice = answer['choices'][0]
                message = choice.get('message')
                if not isinstance(message, dict):
                    raise ValueError('missing assistant message')
                delta = dict(message)
                if 'tool_calls' in delta:
                    delta['tool_calls'] = [dict(call, index=i) for i, call in enumerate(delta['tool_calls'])]
                chunk = {'id': answer.get('id', f'arena-{index}'), 'object': 'chat.completion.chunk',
                         'choices': [{'index': 0, 'delta': delta, 'finish_reason': choice.get('finish_reason')}]}
                payload = ('data: ' + json.dumps(chunk) + '\n\ndata: [DONE]\n\n').encode()
                with lock:
                    state['responses'] += 1
                self.respond(200, payload, event=True)
            except (OSError, ValueError, KeyError, TypeError, AttributeError, TimeoutError) as error:
                failure = 'provider_error'
                evidence = {'exception_type': type(error).__name__}
                if isinstance(error, urllib.error.HTTPError):
                    evidence['http_status'] = error.code
                    try:
                        raw = error.read(65537)
                    except OSError as body_error:
                        evidence['body_read_error'] = type(body_error).__name__
                        raw = b''
                    text = raw[:65536].decode('utf-8', errors='replace')
                    if api_key:
                        text = text.replace(api_key, '[REDACTED]')
                    evidence['body'] = text
                    evidence['body_truncated'] = len(raw) > 65536
                    try:
                        detail = json.loads(text).get('error', {})
                        # Typed protocol codes only: do not classify from prose
                        # that could contain model output or task instructions.
                        if isinstance(detail, dict) and (
                            detail.get('code') in ('context_length_exceeded', 'context_window_exceeded')
                            or detail.get('type') == 'exceed_context_size_error'
                        ):
                            failure = 'context_exhausted'
                    except (ValueError, AttributeError):
                        pass
                if time.monotonic() >= deadline:
                    failure = 'timeout'
                if index is not None:
                    (logs / f'error-{index}.json').write_text(json.dumps(evidence) + '\n')
                with lock:
                    state['usage_complete'] = False
                    if state['failure'] is None:
                        state['failure'] = failure
                try:
                    self.respond(502, b'{"error":{"message":"arena upstream request failed"}}')
                except OSError:
                    pass

    server = ThreadingHTTPServer(('127.0.0.1', 0), Gateway)
    server.daemon_threads = True
    worker = threading.Thread(target=server.serve_forever, kwargs={'poll_interval': .05}, daemon=True)
    worker.start()
    env = {'PATH': os.environ.get('PATH', '/usr/local/bin:/usr/bin:/bin'),
           'HOME': str(home), 'XDG_CONFIG_HOME': str(home / '.config'),
           'KEEL_BASE_URL': f'http://127.0.0.1:{server.server_port}/v1',
           'KEEL_MODEL': config['model'],
           'LANG': 'C.UTF-8'}
    if config['thinking'] is not None:
        env['KEEL_THINKING'] = '1' if config['thinking'] else '0'
    command = [str(binary), 'run', '--json', '--yolo', '--no-toolchains',
               '--root', config['root'], '--max-context-tokens', str(config['context_tokens']),
               '--log', str(logs / 'session.jsonl'), '--', instruction]
    process = None
    previous = {}

    def cancel(signum, frame):
        raise InterruptedError('runtime cancelled')

    for signum in (signal.SIGTERM, signal.SIGINT):
        previous[signum] = signal.signal(signum, cancel)
    try:
        with (logs / 'stdout.jsonl').open('xb') as stdout, (logs / 'stderr.txt').open('xb') as stderr:
            process = subprocess.Popen(command, env=env, cwd=config['root'], stdout=stdout,
                                       stderr=stderr, start_new_session=True)
            code = process.wait(timeout=max(.01, deadline - time.monotonic()))
    except subprocess.TimeoutExpired:
        state['failure'] = 'timeout'
        code = 124
    except InterruptedError:
        state['failure'] = 'cancelled'
        code = 130
    except OSError:
        state['failure'] = 'launch_error'
        code = 126
    finally:
        if process is not None:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait()
        server.shutdown()
        server.server_close()
        worker.join(timeout=1)
        for signum, handler in previous.items():
            signal.signal(signum, handler)
    if state['requests'] == 0 or state['requests'] != state['responses']:
        state['usage_complete'] = False
    if not state['usage_complete']:
        state['input_tokens'] = state['output_tokens'] = None
    status = state['failure'] or ('completed' if code == 0 else 'agent_error')
    metadata = {**state, 'status': status, 'exit_code': code,
                'binary_sha256': config['binary_sha256'],
                'policy': {k: config[k] for k in ('max_model_requests', 'max_output_tokens', 'temperature', 'top_p', 'seed', 'thinking', 'context_tokens', 'timeout_seconds')},
                'transport': 'nonstreaming-upstream-sse-envelope'}
    (logs / 'runtime.json').write_text(json.dumps(metadata, indent=2) + '\n')
    if status == 'timeout':
        return 124
    return code if status == 'completed' else (code or 1)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', required=True)
    args = parser.parse_args()
    try:
        with Path(args.config).open('rb') as source:
            return run(read_json(source))
    except (OSError, ValueError):
        print('arena runtime: invalid configuration or unavailable execution environment')
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
