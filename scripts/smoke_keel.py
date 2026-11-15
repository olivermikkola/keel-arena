#!/usr/bin/env python3
"""Opt-in real Keel execution proof against a scripted provider, without inference."""

import argparse
import hashlib
import json
import os
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--binary', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True, help='new private proof directory outside public Git')
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=False, mode=0o700)
    workspace = args.out / 'workspace'
    workspace.mkdir()
    requests = []
    expected = 'Keel Arena scripted provider proof\n'

    class Provider(BaseHTTPRequestHandler):
        def log_message(self, *unused):
            pass

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            requests.append(body)
            if len(requests) == 1:
                names = [tool['function']['name'] for tool in body.get('tools', [])]
                if 'write_file' not in names:
                    self.send_error(400, 'required write_file tool not advertised')
                    return
                message = {'role': 'assistant', 'content': None, 'tool_calls': [
                    {'id': 'proof-write', 'type': 'function', 'function': {
                        'name': 'write_file', 'arguments': json.dumps({'path': 'proof.txt', 'content': expected})}}]}
                finish = 'tool_calls'
            else:
                message = {'role': 'assistant', 'content': 'Finished.'}
                finish = 'stop'
            answer = {'id': 'scripted-proof', 'object': 'chat.completion',
                      'choices': [{'index': 0, 'message': message, 'finish_reason': finish}],
                      'usage': {'prompt_tokens': 10, 'completion_tokens': 5}}
            raw = json.dumps(answer).encode()
            self.send_response(200)
            self.send_header('Content-Length', str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)
    server = ThreadingHTTPServer(('127.0.0.1', 0), Provider)
    thread = threading.Thread(target=server.serve_forever, kwargs={'poll_interval': .01})
    thread.start()
    try:
        binary = args.binary.resolve()
        with binary.open('rb') as source:
            digest = hashlib.file_digest(source, 'sha256').hexdigest()
        config = {'binary': str(binary), 'binary_sha256': digest,
                  'root': str(workspace.resolve()), 'home': str((args.out / 'home').resolve()),
                  'logs': str((args.out / 'logs').resolve()), 'model': 'scripted-proof',
                  'base_url': f'http://127.0.0.1:{server.server_port}/v1',
                  'max_model_requests': 3, 'max_output_tokens': 256, 'context_tokens': 16384,
                  'temperature': 0.0, 'top_p': 1.0, 'seed': 0, 'thinking': None, 'timeout_seconds': 15}
        path = args.out / 'config.json'
        path.write_text(json.dumps(config))
        env = {**os.environ, 'ARENA_INSTRUCTION': 'Create proof.txt containing the requested proof text.'}
        env.pop('KEEL_API_KEY', None)
        result = subprocess.run([sys.executable, '-m', 'keel_arena.runtime', '--config', str(path.resolve())],
                                env=env, cwd=ROOT, capture_output=True, text=True, timeout=25)
        artifact = workspace / 'proof.txt'
        passed = result.returncode == 0 and artifact.is_file() and artifact.read_text() == expected
        observed = len(requests) == 2 and any(m.get('role') == 'tool' for m in requests[-1].get('messages', []))
        report = {'kind': 'scripted-provider-integration-proof', 'model_inference': False,
                  'passed': passed and observed, 'binary_sha256': digest,
                  'provider_requests': len(requests), 'tool_result_replayed': observed}
        (args.out / 'proof.json').write_text(json.dumps(report, indent=2) + '\n')
        print(json.dumps(report, indent=2))
        return 0 if report['passed'] else 1
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


if __name__ == '__main__':
    raise SystemExit(main())
