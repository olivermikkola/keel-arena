import hashlib
import importlib.util
import json
import os
import shutil
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


def _gauntlet_tasks():
    manifest = json.loads((ROOT / 'tasks/gauntlet/manifest.json').read_text())
    return [(name, ROOT / 'tasks/gauntlet' / name) for name in sorted(manifest['tasks'])]


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

    def test_gauntlet_broken_fixed_and_forged_controls(self):
        for name, task in _gauntlet_tasks():
            verifier = judge(task)
            config = tomllib.loads((task / 'task.toml').read_text())
            artifacts = config['artifacts']
            with self.subTest(task=name):
                with tempfile.TemporaryDirectory() as tmp:
                    ws = Path(tmp) / 'ws'
                    shutil.copytree(task / 'environment/workspace', ws)
                    # Broken (nop) control: untouched workspace must not pass all checks.
                    if len(artifacts) == 1 and artifacts[0]['destination'] in (
                        'indexer.py', 'validator.py', 'report.json', 'summary.json',
                        'triage.json', 'normalized.json', 'migrated.json', 'answers.json',
                        'trace_report.json', 'brief.md', 'review.md',
                    ):
                        target_nop = ws / artifacts[0]['destination']
                        nop_res = verifier.evaluate(target_nop, isolate=False)
                    else:
                        nop_res = verifier.evaluate(ws, isolate=False)
                    self.assertLess(nop_res['passed'], nop_res['total'])

                    # Fixed (oracle) control: applying solution/ files must pass 100%.
                    sol_ws = Path(tmp) / 'sol'
                    shutil.copytree(task / 'environment/workspace', sol_ws)
                    for item in (task / 'solution').iterdir():
                        if item.name == 'solve.sh':
                            continue
                        if (sol_ws / 'manifests' / item.name).exists():
                            shutil.copy2(item, sol_ws / 'manifests' / item.name)
                        elif (sol_ws / 'deploy' / item.name).exists():
                            shutil.copy2(item, sol_ws / 'deploy' / item.name)
                        else:
                            shutil.copy2(item, sol_ws / item.name)
                    if len(artifacts) == 1 and artifacts[0]['destination'] != 'postmortem.json':
                        sol_res = verifier.evaluate(sol_ws / artifacts[0]['destination'], isolate=False)
                    else:
                        sol_res = verifier.evaluate(sol_ws, isolate=False)
                    self.assertEqual(sol_res['passed'], sol_res['total'])

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

        for name, task in _gauntlet_tasks():
            with self.subTest(task=name):
                config = tomllib.loads((task / 'task.toml').read_text())
                self.assertEqual(config['verifier']['environment_mode'], 'separate')
                self.assertEqual(config['verifier']['user'], 'root')
                self.assertEqual(config['environment']['network_mode'], 'no-network')
                self.assertIn('@sha256:', (task / 'environment/Dockerfile').read_text())
                self.assertTrue((task / 'instruction.md').is_file())
                self.assertTrue((task / 'solution/solve.sh').is_file())
                self.assertTrue((task / 'tests/test.sh').is_file())
                if config['metadata'].get('judge_mode') == 'hybrid':
                    self.assertTrue((task / 'tests/rubric.json').is_file())

    def test_public_pack_manifest_matches_all_published_task_bytes(self):
        for manifest_path, root_dir in (
            (ROOT / 'tasks/repair/manifest.json', ROOT / 'tasks/repair'),
            (ROOT / 'tasks/gauntlet/manifest.json', ROOT / 'tasks/gauntlet'),
        ):
            manifest = json.loads(manifest_path.read_text())
            for name, item in manifest['tasks'].items():
                task = root_dir / name
                actual = {path.relative_to(task).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
                          for path in task.rglob('*') if path.is_file() and '__pycache__' not in path.parts}
                self.assertEqual(actual, item['files'])
                digest = hashlib.sha256(json.dumps(actual, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
                self.assertEqual(digest, item['snapshot_sha256'])

    def test_suites_index_matches_directories(self):
        index = json.loads((ROOT / 'tasks/suites.json').read_text())
        self.assertEqual(len(index['tasks']), 16)
        for tid, meta in index['tasks'].items():
            tdir = ROOT / 'tasks' / meta['path']
            self.assertTrue((tdir / 'task.toml').is_file(), tid)

    def test_pinned_harbor_task_schema(self):
        try:
            from harbor.models.task.config import TaskConfig
        except ImportError:
            if os.environ.get('ARENA_REQUIRE_HARBOR'):
                raise
            self.skipTest('optional harbor==0.26.0 not installed')
        all_tasks = list(p for p in (ROOT / 'tasks/repair').iterdir() if p.is_dir())
        all_tasks.extend(task for _, task in _gauntlet_tasks())
        for task in all_tasks:
            data = tomllib.loads((task / 'task.toml').read_text())
            config = TaskConfig.model_validate(data)
            self.assertEqual(config.verifier.environment_mode.value, 'separate')
