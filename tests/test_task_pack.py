import importlib.util
import json
import os
import tempfile
import tomllib
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def judge(task):
    spec = importlib.util.spec_from_file_location('arena_task_judge', task / 'tests/judge.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TaskPackTest(unittest.TestCase):
    def test_broken_fixed_and_forged_candidates(self):
        for task in sorted(p for p in (ROOT / 'tasks/repair').iterdir() if p.is_dir()):
            verifier = judge(task)
            with self.subTest(task=task.name):
                broken = verifier.evaluate(task / 'environment/workspace/main.py', isolate=False)
                fixed = verifier.evaluate(task / 'solution/fixed.py', isolate=False)
                self.assertLess(broken['passed'], broken['total'])
                self.assertEqual(fixed['passed'], fixed['total'])
                with tempfile.TemporaryDirectory() as directory:
                    fake = Path(directory) / 'fake.py'
                    fake.write_text('print(\'{"ok": true, "passed": 999}\')\n')
                    result = verifier.evaluate(fake, isolate=False)
                    self.assertEqual(result['passed'], 0)
                    fake.unlink()
                    fake.symlink_to(task / 'solution/fixed.py')
                    self.assertEqual(verifier.evaluate(fake, isolate=False)['passed'], 0)

    def test_task_configuration_and_build_context_hide_controls(self):
        for task in (p for p in (ROOT / 'tasks/repair').iterdir() if p.is_dir()):
            config = tomllib.loads((task / 'task.toml').read_text())
            self.assertEqual(config['verifier']['environment_mode'], 'separate')
            self.assertEqual(config['verifier']['user'], 'root')
            self.assertEqual(config['environment']['network_mode'], 'no-network')
            self.assertEqual(config['artifacts'], [{'source': '/workspace/main.py', 'destination': 'main.py'}])
            environment_files = {p.relative_to(task / 'environment').as_posix()
                                 for p in (task / 'environment').rglob('*') if p.is_file()}
            self.assertEqual(environment_files, {'Dockerfile', 'workspace/main.py'})
            self.assertIn('@sha256:', (task / 'environment/Dockerfile').read_text())

    def test_public_pack_manifest_matches_all_published_task_bytes(self):
        import hashlib
        manifest = json.loads((ROOT / 'tasks/repair/manifest.json').read_text())
        for name, item in manifest['tasks'].items():
            task = ROOT / 'tasks/repair' / name
            actual = {path.relative_to(task).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
                      for path in task.rglob('*') if path.is_file() and '__pycache__' not in path.parts}
            self.assertEqual(actual, item['files'])
            digest = hashlib.sha256(json.dumps(actual, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
            self.assertEqual(digest, item['snapshot_sha256'])

    def test_pinned_harbor_task_schema(self):
        try:
            from harbor.models.task.config import TaskConfig
        except ImportError:
            if os.environ.get('ARENA_REQUIRE_HARBOR'):
                raise
            self.skipTest('optional harbor==0.26.0 not installed')
        for task in (p for p in (ROOT / 'tasks/repair').iterdir() if p.is_dir()):
            data = tomllib.loads((task / 'task.toml').read_text())
            config = TaskConfig.model_validate(data)
            self.assertEqual(config.verifier.environment_mode.value, 'separate')
