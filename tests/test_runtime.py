import hashlib
import json
import os
import signal
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from keel_arena.runtime import validate_config

ROOT = Path(__file__).resolve().parents[1]


class RuntimeTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.requests = []
        self.provider_error = None
        self.provider_delay = 0
        owner = self
        requests = self.requests

        class Provider(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                requests.append((body, self.headers.get('Authorization')))
                if owner.provider_delay:
                    import time
                    time.sleep(owner.provider_delay)
                if owner.provider_error is not None:
                    payload = json.dumps(owner.provider_error).encode()
                    self.send_response(400)
                    self.send_header('Content-Length', str(len(payload)))
                    self.end_headers()
                    try:
                    self.wfile.write(payload)
                except BrokenPipeError:
                    pass
                    return
                answer = {'choices': [{'message': {'role': 'assistant', 'content': 'done'},
                                       'finish_reason': 'stop'}],
                          'usage': {'prompt_tokens': 10, 'completion_tokens': 2}}
                payload = json.dumps(answer).encode()
                self.send_response(200)
                self.send_header('Content-Length', str(len(payload)))
                self.end_headers()
                try:
                    self.wfile.write(payload)
                except BrokenPipeError:
                    pass
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Provider)
        thread = threading.Thread(target=self.server.serve_forever, kwargs={'poll_interval': .01})
        thread.start()
        self.addCleanup(thread.join)
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)

    def launch(self, agent_body, **overrides):
        binary = self.root / 'agent'
        binary.write_text(f'#!{sys.executable}\n' + agent_body)
        binary.chmod(0o755)
        self.config = {'binary': str(binary), 'binary_sha256': hashlib.sha256(binary.read_bytes()).hexdigest(),
                       'root': str(self.root), 'home': str(self.root / 'isolated-home'),
                       'logs': str(self.root / 'logs'), 'model': 'fixture-model',
                       'base_url': f'http://127.0.0.1:{self.server.server_port}/v1',
                       'context_tokens': 1024, 'max_model_requests': 1, 'max_output_tokens': 128,
                       'temperature': 0.0, 'top_p': 1.0, 'seed': 7, 'thinking': False,
                       'timeout_seconds': 3, **overrides}
        path = self.root / 'runtime-config.json'
        path.write_text(json.dumps(self.config))
        env = {**os.environ, 'ARENA_INSTRUCTION': 'synthetic test', 'KEEL_API_KEY': 'fixture-secret',
               'PRIVATE_SENTINEL': 'must-not-reach-agent'}
        result = subprocess.run([sys.executable, '-m', 'keel_arena.runtime', '--config', str(path)],
                                env=env, capture_output=True, text=True, cwd=ROOT, timeout=10)
        metadata = self.root / 'logs/runtime.json'
        self.metadata = json.loads(metadata.read_text()) if metadata.exists() else None
        return result

    REQUEST = '''import json, os, urllib.request
assert 'PRIVATE_SENTINEL' not in os.environ
assert 'KEEL_API_KEY' not in os.environ
req = urllib.request.Request(os.environ['KEEL_BASE_URL'] + '/chat/completions',
    data=json.dumps({'model': 'untrusted', 'messages': [{'role': 'user', 'content': 'test'}],
                     'max_tokens': 999999, 'temperature': 2, 'stream': True}).encode(),
    headers={'Content-Type': 'application/json'})
with urllib.request.urlopen(req) as response:
    assert b'[DONE]' in response.read()
'''

    def test_actual_subprocess_gateway_limits_policy_and_credentials(self):
        result = self.launch(self.REQUEST)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        body, auth = self.requests[0]
        self.assertEqual(body['max_tokens'], 128)
        self.assertEqual(body['temperature'], 0)
        self.assertEqual(body['seed'], 7)
        self.assertEqual(body['model'], 'fixture-model')
        self.assertFalse(body['stream'])
        self.assertEqual(auth, 'Bearer fixture-secret')
        self.assertEqual(self.metadata['input_tokens'], 10)
        self.assertEqual(self.metadata['output_tokens'], 2)
        self.assertEqual(self.metadata['status'], 'completed')
        self.assertNotIn('fixture-secret', (self.root / 'logs/completion-1.json').read_text())

    def test_request_budget_is_enforced_independently_of_agent_exit(self):
        # Agent deliberately catches the HTTP failure and exits zero.
        result = self.launch(self.REQUEST + '''
try:
    urllib.request.urlopen(req)
except Exception:
    pass
''')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(len(self.requests), 1)
        self.assertEqual(self.metadata['status'], 'budget_exhausted')

    def test_wall_timeout_terminates_agent_group(self):
        result = self.launch('import time\ntime.sleep(20)\n', timeout_seconds=1)
        self.assertEqual(result.returncode, 124)
        self.assertEqual(self.metadata['status'], 'timeout')
        self.assertIsNone(self.metadata['input_tokens'])

    def test_wrong_binary_and_invalid_sampling_are_refused(self):
        result = self.launch('pass\n', binary_sha256='0' * 64)
        self.assertEqual(result.returncode, 2)
        self.assertEqual(len(self.requests), 0)
        self.assertIsNone(self.metadata)
        self.config['thinking'] = 'false'
        with self.assertRaises(ValueError):
            validate_config(self.config)

    def test_private_provider_errors_are_bounded_redacted_and_typed(self):
        self.provider_error = {'error': {'type': 'exceed_context_size_error',
                                         'message': 'too long; token fixture-secret'}}
        result = self.launch(self.REQUEST)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.metadata['status'], 'context_exhausted')
        self.assertIsNone(self.metadata['input_tokens'])
        evidence = json.loads((self.root / 'logs/error-1.json').read_text())
        self.assertEqual(evidence['http_status'], 400)
        self.assertNotIn('fixture-secret', evidence['body'])
        self.assertIn('[REDACTED]', evidence['body'])
        self.assertTrue((self.root / 'logs/request-1.json').is_file())

    def test_provider_prose_cannot_reclassify_an_error(self):
        self.provider_error = {'error': {'message': 'context_length_exceeded'}}
        result = self.launch(self.REQUEST)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.metadata['status'], 'provider_error')

    def test_oversized_error_body_is_preserved_as_a_bounded_prefix(self):
        self.provider_error = {'error': {'message': 'x' * 70000}}
        self.launch(self.REQUEST)
        evidence = json.loads((self.root / 'logs/error-1.json').read_text())
        self.assertTrue(evidence['body_truncated'])
        self.assertLessEqual(len(evidence['body'].encode()), 65536)

    def test_inflight_timeout_does_not_claim_zero_token_usage(self):
        self.provider_delay = 2
        result = self.launch(self.REQUEST, timeout_seconds=1)
        self.assertEqual(result.returncode, 124)
        self.assertEqual(len(self.requests), 1)
        self.assertEqual(self.metadata['requests'], 1)
        self.assertEqual(self.metadata['responses'], 0)
        self.assertIsNone(self.metadata['input_tokens'])
        self.assertIsNone(self.metadata['output_tokens'])
