import asyncio
import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

try:
    from keel_arena.harbor_agent import AgentTimeoutError, KeelAgent
    from harbor.agents.installed.base import ApiError, NonZeroAgentExitCodeError
    from harbor.models.agent.context import AgentContext
except ImportError:
    if os.environ.get('ARENA_REQUIRE_HARBOR'):
        raise
    KeelAgent = None


@unittest.skipIf(KeelAgent is None, 'optional harbor==0.26.0 not installed')
class HarborAgentTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.binary = self.root / 'fixture-agent'
        self.binary.write_bytes(b'original synthetic executable fixture')
        self.hash = hashlib.sha256(self.binary.read_bytes()).hexdigest()

    def agent(self, **kwargs):
        return KeelAgent(logs_dir=self.root, binary_path=self.binary, binary_sha256=self.hash,
                         model_name='openai/fixture', base_url='http://provider.example/v1',
                         extra_env={'KEEL_API_KEY': 'fixture-secret'}, **kwargs)

    def test_real_sdk_setup_and_run_contract(self):
        agent = self.agent(skip_install=True)
        commands, uploads = [], []

        class Environment:
            default_user = None

            async def exec(self, **kwargs):
                commands.append(kwargs)
                if kwargs['command'].startswith('cat '):
                    return SimpleNamespace(return_code=0, stdout='{"status":"completed"}', stderr='')
                return SimpleNamespace(return_code=0, stdout='', stderr='')

            async def upload_file(self, source, destination):
                uploads.append((destination, Path(source).read_bytes()))
        env = Environment()
        asyncio.run(agent.configure(env))
        asyncio.run(agent.run('prompt; $(not-a-command)', env, AgentContext()))
        self.assertIn('/installed-agent/arena-runtime.py', [p for p, _ in uploads])
        config = json.loads(next(raw for path, raw in uploads if path.endswith('arena-run.json')))
        self.assertEqual(config['binary_sha256'], self.hash)
        launch = next(c for c in commands if 'python3 /installed-agent/arena-runtime.py' in c['command'])
        self.assertEqual(launch['env']['ARENA_INSTRUCTION'], 'prompt; $(not-a-command)')
        self.assertEqual(launch['env']['KEEL_API_KEY'], 'fixture-secret')
        self.assertNotIn('fixture-secret', launch['command'])
        self.assertNotIn('not-a-command', launch['command'])

    def test_binary_identity_and_invalid_policy_fail_before_execution(self):
        self.binary.write_bytes(b'changed')
        with self.assertRaises(ValueError):
            self.agent()
        self.hash = hashlib.sha256(self.binary.read_bytes()).hexdigest()
        for kwargs in ({'max_model_requests': 0}, {'thinking': 'false'}, {'top_p': 2}):
            with self.assertRaises(ValueError):
                self.agent(**kwargs)

    def test_usage_is_actual_and_unknown_stays_unknown(self):
        path = self.root / 'run'
        path.mkdir()
        (path / 'runtime.json').write_text('{"input_tokens":23,"output_tokens":null,"status":"completed"}')
        context = AgentContext()
        self.agent().populate_context_post_run(context)
        self.assertEqual(context.n_input_tokens, 23)
        self.assertIsNone(context.n_output_tokens)

    def test_provider_timeout_and_budget_classification(self):
        for status, expected in [('provider_error', ApiError), ('timeout', AgentTimeoutError),
                                 ('budget_exhausted', NonZeroAgentExitCodeError)]:
            class Environment:
                default_user = None

                async def exec(self, **kwargs):
                    if kwargs['command'].startswith('cat '):
                        return SimpleNamespace(return_code=0, stdout=json.dumps({'status': status}), stderr='')
                    return SimpleNamespace(return_code=1, stdout='', stderr='')

                async def upload_file(self, source, destination):
                    pass
            with self.subTest(status=status), self.assertRaises(expected):
                asyncio.run(self.agent().run('fixture', Environment(), AgentContext()))
