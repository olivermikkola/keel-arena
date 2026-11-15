"""Original synthetic backend fixtures; never a claim of measured model results."""

import copy
import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from keel_arena.harbor_import import canonical_hash, import_trials
from keel_arena.results import InvalidResult, summarize

ROOT = Path(__file__).resolve().parents[1]


class HarborImportTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        sample = json.loads((ROOT / 'examples/synthetic-results.json').read_text())
        self.plan = {k: v for k, v in sample.items() if k != 'attempts'}
        self.manifest = {'schema_version': 1, 'harbor_version': '0.26.0',
                         'reward_metric': 'reward', 'plan': self.plan, 'trials': []}
        for index, attempt in enumerate(sample['attempts']):
            directory = f'trial-{index}'
            config = {'agent': {'model_name': attempt['contestant']},
                      'verifier': {'disable': False}, 'install_only': False}
            binding = {k: attempt[k] for k in ('task', 'contestant', 'repetition')}
            binding.update(directory=directory, task_checksum='native-fixture-checksum',
                           config_sha256=canonical_hash(config))
            self.manifest['trials'].append(binding)
            trial = {'schema_version': 1, 'task_name': attempt['task'],
                     'task_checksum': binding['task_checksum'], 'config': config,
                     'started_at': '2026-11-15T00:00:00Z',
                     'finished_at': '2026-11-15T00:00:10Z',
                     'reward_valid': True, 'exception_info': None,
                     'verifier_result': {'rewards': {'reward': 1 if attempt['outcome'] == 'solved' else 0}},
                     'agent_result': {'n_input_tokens': None, 'n_output_tokens': 8}}
            if attempt['outcome'] == 'infrastructure_error':
                trial['exception_info'] = {'exception_type': 'EnvironmentStartError'}
                trial['reward_valid'] = False
            dest = self.root / directory
            (dest / 'verifier').mkdir(parents=True)
            (dest / 'verifier/reward.txt').write_text(str(trial['verifier_result']['rewards']['reward']))
            (dest / 'result.json').write_text(json.dumps(trial))

    def change_trial(self, update):
        path = self.root / 'trial-0/result.json'
        trial = json.loads(path.read_text())
        update(trial)
        path.write_text(json.dumps(trial))

    def test_import_real_files_and_cli_roundtrip(self):
        output = import_trials(self.manifest, self.root)
        report = summarize(output)
        self.assertEqual(report['matched_blocks'], 2)
        self.assertEqual(report['union_solved_blocks'], 2)
        self.assertEqual(output['attempts'][0]['wall_seconds'], 10)
        self.assertEqual(output['attempts'][0]['verifier_result_sha256'],
                         hashlib.sha256((self.root / 'trial-0/result.json').read_bytes()).hexdigest())
        self.assertIsNone(output['attempts'][0]['input_tokens'])
        self.assertEqual(report['contestants']['demo-a']['matched_output_tokens'], 16)
        manifest_path = self.root / 'manifest.json'
        manifest_path.write_text(json.dumps(self.manifest))
        result = subprocess.run([sys.executable, '-m', 'keel_arena', 'import-harbor',
                                 str(manifest_path), '--jobs-root', str(self.root)],
                                capture_output=True, text=True, check=True, cwd=ROOT)
        self.assertEqual(json.loads(result.stdout), output)

    def test_mismatched_config_task_or_completion_is_refused(self):
        for update in (lambda t: t['config']['agent'].update(model_name='other-model'),
                       lambda t: t.update(task_checksum='wrong'),
                       lambda t: t.update(task_name='other-task'),
                       lambda t: t.update(finished_at=None),
                       lambda t: t.update(step_results=[{'step_name': 'next'}])):
            with self.subTest(update=update):
                original = (self.root / 'trial-0/result.json').read_bytes()
                self.change_trial(update)
                with self.assertRaises(InvalidResult):
                    import_trials(self.manifest, self.root)
                (self.root / 'trial-0/result.json').write_bytes(original)

    def test_forged_or_missing_rewards_are_refused(self):
        reward = self.root / 'trial-0/verifier/reward.txt'
        for value in ('0', 'nan', '2'):
            reward.write_text(value)
            with self.assertRaises(InvalidResult):
                import_trials(self.manifest, self.root)
        reward.unlink()
        with self.assertRaises(InvalidResult):
            import_trials(self.manifest, self.root)

    def test_json_reward_and_trajectory_hash(self):
        directory = self.root / 'trial-0'
        (directory / 'verifier/reward.txt').unlink()
        (directory / 'verifier/reward.json').write_text('{"reward": 1}')
        (directory / 'agent').mkdir()
        raw = b'{"synthetic": true}'
        (directory / 'agent/trajectory.json').write_bytes(raw)
        output = import_trials(self.manifest, self.root)
        self.assertEqual(output['attempts'][0]['trajectory_sha256'], hashlib.sha256(raw).hexdigest())

    def test_timeout_and_unknown_errors_never_count_as_solves(self):
        for kind, expected in [('AgentTimeoutError', 'timeout'), ('NewBackendError', 'infrastructure_error')]:
            self.change_trial(lambda t: t.update(exception_info={'exception_type': kind}))
            output = import_trials(self.manifest, self.root)
            self.assertEqual(output['attempts'][0]['outcome'], expected)

    def test_known_agent_failures_are_graded_not_excluded(self):
        self.change_trial(lambda t: t.update(
            exception_info={'exception_type': 'ContextWindowExceededError'},
            verifier_result={'rewards': {'reward': 0}}))
        (self.root / 'trial-0/verifier/reward.txt').write_text('0')
        result = import_trials(self.manifest, self.root)
        self.assertEqual(result['attempts'][0]['outcome'], 'unsolved')
        self.assertEqual(summarize(result)['matched_blocks'], 2)

    def test_paths_symlinks_duplicate_bindings_and_unknown_version_refused(self):
        for mutate in (lambda m: m['trials'][0].update(directory='../outside'),
                       lambda m: m['trials'][0].update(directory='/outside'),
                       lambda m: m['trials'].pop(),
                       lambda m: m['trials'].__setitem__(1, copy.deepcopy(m['trials'][0])),
                       lambda m: m.update(harbor_version='future')):
            manifest = copy.deepcopy(self.manifest)
            mutate(manifest)
            with self.assertRaises(InvalidResult):
                import_trials(manifest, self.root)
        path = self.root / 'trial-0/result.json'
        content = path.read_bytes()
        path.unlink()
        target = self.root / 'elsewhere.json'
        target.write_bytes(content)
        path.symlink_to(target)
        with self.assertRaises(InvalidResult):
            import_trials(self.manifest, self.root)

    def test_real_harbor_sdk_serialization(self):
        try:
            from harbor.models.trial.result import TrialResult
        except ImportError:
            import os
            if os.environ.get("ARENA_REQUIRE_HARBOR"):
                raise
            self.skipTest('optional harbor==0.26.0 not installed')
        # Let the real SDK serialize its required config and computed fields.
        trial = TrialResult(
            task_name='toy-repair', trial_name='trial-0', trial_uri='file:///fixture',
            task_id={'path': 'toy-repair'}, task_checksum='native-fixture-checksum',
            config={'task': {'path': 'toy-repair'}, 'verifier': {'disable': False}},
            agent_info={'name': 'fixture', 'version': '1'},
            verifier_result={'rewards': {'reward': 1}},
            started_at='2026-11-15T00:00:00Z', finished_at='2026-11-15T00:00:10Z')
        raw = trial.model_dump(mode='json')
        (self.root / 'trial-0/result.json').write_text(json.dumps(raw))
        self.manifest['trials'][0]['config_sha256'] = canonical_hash(raw['config'])
        self.assertEqual(import_trials(self.manifest, self.root)['attempts'][0]['outcome'], 'solved')
