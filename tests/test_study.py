import asyncio
import copy
import hashlib
import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from keel_arena.harbor_import import canonical_hash
from keel_arena.results import InvalidResult
from keel_arena.study import _cancel_and_drain, execute, freeze, read_document

ROOT = Path(__file__).resolve().parents[1]
HAS_HARBOR = importlib.util.find_spec('harbor') is not None
if os.environ.get('ARENA_REQUIRE_HARBOR') and not HAS_HARBOR:
    raise ImportError('required Harbor SDK missing')


@unittest.skipUnless(HAS_HARBOR, 'optional harbor==0.26.0 not installed')
class StudyTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.binary = self.root / 'binary'
        self.binary.write_bytes(b'original synthetic executable for freeze tests')
        self.output = self.root / 'study'
        self.settings = {
            'schema_version': 1, 'purpose': 'demonstration', 'split': 'development',
            'binary_path': str(self.binary), 'binary_sha256': hashlib.sha256(self.binary.read_bytes()).hexdigest(),
            'tasks': {'config-check': str(ROOT / 'tasks/repair/config-check')},
            'contestants': {name: {'model': 'openai/fixture', 'base_url': 'http://provider.example/v1',
                                   'model_revision_sha256': '1' * 64, 'quantization': 'none', 'api_key_env': None}
                            for name in ('demo-a', 'demo-b')},
            'repetitions': 2,
            'budget': {'max_steps': 2, 'max_output_tokens': 128, 'timeout_seconds': 5},
            'sampling': {'temperature': 0.0, 'top_p': 1.0, 'seed': 7, 'thinking': None, 'context_tokens': 1024},
            'environment': {'type': 'docker', 'allow_agent_hosts': ['provider.example']},
            'thermal_limit_c': None,
        }

    def test_freeze_exact_configs_without_backend_execution(self):
        from harbor.trial.trial import Trial
        with patch.object(Trial, 'create', side_effect=AssertionError('freeze must not execute')):
            report = freeze(self.settings, self.output)
        self.assertEqual(report['planned_attempts'], 4)
        frozen = read_document(self.output / 'frozen.json')
        self.assertEqual([b['contestant'] for b in frozen['manifest']['trials']],
                         ['demo-a', 'demo-b', 'demo-b', 'demo-a'])
        for binding in frozen['manifest']['trials']:
            config = frozen['configs'][binding['directory']]
            self.assertEqual(canonical_hash(config), binding['config_sha256'])
            self.assertEqual(config['agent']['kwargs']['max_model_requests'], 2)
        self.assertEqual(self.output.stat().st_mode & 0o777, 0o700)
        self.assertEqual((self.output / 'frozen.json').stat().st_mode & 0o777, 0o600)
        self.assertFalse((self.output / 'trials').exists())
        second = self.root / 'another-study'
        freeze(self.settings, second)
        other = read_document(second / 'frozen.json')
        self.assertNotEqual(frozen['manifest']['trials'][0]['directory'],
                            other['manifest']['trials'][0]['directory'])

    def test_changed_binary_receipt_and_duplicate_output_are_refused(self):
        freeze(self.settings, self.output)
        with self.assertRaises(InvalidResult):
            freeze(self.settings, self.output)
        self.binary.write_bytes(b'changed')
        with self.assertRaises(InvalidResult):
            asyncio.run(execute(self.output))
        frozen = read_document(self.output / 'frozen.json')
        frozen['thermal_limit_c'] = 68
        (self.output / 'frozen.json').write_text(json.dumps(frozen))
        with self.assertRaises(InvalidResult):
            asyncio.run(execute(self.output))

    def test_invalid_credentials_and_paid_backend_fail_before_output(self):
        for mutate in (lambda s: s['contestants']['demo-a'].update(api_key_env='not-an-env-name'),
                       lambda s: s['environment'].update(type='paid-cloud'),
                       lambda s: s.update(thermal_limit_c=80)):
            settings = copy.deepcopy(self.settings)
            mutate(settings)
            with self.assertRaises((InvalidResult, ValueError)):
                freeze(settings, self.output)
            self.assertFalse(self.output.exists())

    def test_real_sdk_freeze_then_mock_execution_import_and_verified_resume(self):
        from harbor.trial.trial import Trial
        freeze(self.settings, self.output)
        calls = []

        async def create(config):
            calls.append(config.trial_name)

            async def run():
                path = Path(config.trials_dir) / config.trial_name
                (path / 'verifier').mkdir(parents=True)
                (path / 'verifier/reward.txt').write_text('1')
                frozen = read_document(self.output / 'frozen.json')
                binding = next(b for b in frozen['manifest']['trials'] if b['directory'] == config.trial_name)
                data = {'schema_version': 1, 'task_name': binding['task'],
                        'task_checksum': binding['task_checksum'], 'config': config.model_dump(mode='json'),
                        'started_at': '2026-11-15T00:00:00Z', 'finished_at': '2026-11-15T00:00:01Z',
                        'reward_valid': True, 'verifier_result': {'rewards': {'reward': 1}}}
                (path / 'result.json').write_text(json.dumps(data))
            return SimpleNamespace(config=config, run=run)
        with patch.object(Trial, 'create', side_effect=create):
            report = asyncio.run(execute(self.output))
            self.assertEqual(report['matched_blocks'], 2)
            self.assertEqual(len(calls), 4)
            report2 = asyncio.run(execute(self.output, resume=True))
            self.assertEqual(report, report2)
            self.assertEqual(len(calls), 4)
        first = read_document(self.output / 'frozen.json')['manifest']['trials'][0]['directory']
        result_path = self.output / 'trials' / first / 'result.json'
        data = json.loads(result_path.read_text())
        data['config']['agent']['model_name'] = 'changed'
        result_path.write_text(json.dumps(data))
        with self.assertRaises(InvalidResult):
            asyncio.run(execute(self.output, resume=True))

    def test_thermal_refusal_launches_nothing_and_partial_cell_not_overwritten(self):
        from harbor.trial.trial import Trial
        self.settings['thermal_limit_c'] = 65
        freeze(self.settings, self.output)
        with patch('keel_arena.study._temperature', return_value=66), \
                patch.object(Trial, 'create', side_effect=AssertionError('must not launch')):
            report = asyncio.run(execute(self.output))
        self.assertEqual(report['status'], 'thermal_stop')
        self.assertEqual(report['completed'], 0)
        first = read_document(self.output / 'frozen.json')['manifest']['trials'][0]['directory']
        (self.output / 'trials' / first).mkdir(parents=True)
        with self.assertRaises(InvalidResult):
            asyncio.run(execute(self.output, resume=True))

    def test_shielded_real_sdk_environment_cleanup_is_drained(self):
        from harbor.environments.docker.docker import DockerEnvironment
        stopped = []

        async def prepare():
            await asyncio.sleep(.02)

        async def compose(command):
            stopped.append(command)

        fake = SimpleNamespace(
            _stream_handle=None, _keep_containers=False, _stream_compose_temp_dir=None,
            prepare_logs_for_host=prepare, _run_docker_compose_command=compose,
            _cleanup_mounts_compose_file=lambda: None, _cleanup_resources_compose_file=lambda: None,
            _cleanup_env_compose_file=lambda: None, _cleanup_egress_control_services_compose_file=lambda: None)

        async def scenario():
            worker = asyncio.create_task(asyncio.sleep(10))
            cleanup = asyncio.create_task(DockerEnvironment.stop(fake, delete=True))
            await _cancel_and_drain(worker)
            self.assertTrue(cleanup.done())
            self.assertTrue(stopped)
        asyncio.run(scenario())

    def test_cli_thermal_stop_has_distinct_exit_code(self):
        from contextlib import redirect_stdout
        from io import StringIO
        from keel_arena.__main__ import main
        self.settings['thermal_limit_c'] = 65
        freeze(self.settings, self.output)
        with patch('keel_arena.study._temperature', return_value=66), redirect_stdout(StringIO()) as output:
            code = main(['run-study', str(self.output)])
        self.assertEqual(code, 3)
        self.assertEqual(json.loads(output.getvalue())['completed'], 0)
