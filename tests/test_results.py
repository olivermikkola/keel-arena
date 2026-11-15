import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from keel_arena.results import InvalidResult, load, summarize, validate

ROOT = Path(__file__).resolve().parents[1]


class ResultsTest(unittest.TestCase):
    def setUp(self):
        self.data = json.loads((ROOT / 'examples/synthetic-results.json').read_text())

    def test_comparison_excludes_whole_infrastructure_block(self):
        report = summarize(self.data)
        self.assertEqual(report['matched_blocks'], 2)
        self.assertEqual(report['excluded_blocks'], 1)
        self.assertEqual(report['union_solved_blocks'], 2)
        self.assertEqual(report['pairwise'], [{
            'left': 'demo-a', 'right': 'demo-b', 'left_only_solved': 1,
            'right_only_solved': 1, 'both_solved': 0}])
        for result in report['contestants'].values():
            self.assertEqual(result['matched_solve_rate'], .5)
            self.assertIsNone(result['matched_input_tokens'])

    def test_reject_incomplete_and_duplicate_matrices(self):
        self.data['attempts'].pop()
        with self.assertRaises(InvalidResult):
            summarize(self.data)
        self.setUp()
        self.data['attempts'][-1] = copy.deepcopy(self.data['attempts'][0])
        with self.assertRaises(InvalidResult):
            validate(self.data)

    def test_reject_unknown_fields_and_unverified_success(self):
        self.data['endpoint'] = 'private-value'
        with self.assertRaises(InvalidResult):
            validate(self.data)
        del self.data['endpoint']
        self.data['attempts'][0]['verifier_result_sha256'] = None
        with self.assertRaises(InvalidResult):
            validate(self.data)

    def test_reject_mixed_evaluation_and_training_splits(self):
        self.data["tasks"]["toy-repair"]["split"] = "train"
        with self.assertRaises(InvalidResult):
            validate(self.data)

    def test_invalid_numeric_inputs(self):
        for value in (True, -1, float('nan'), float('inf'), '10', 10**400):
            with self.subTest(value_type=type(value).__name__):
                data = copy.deepcopy(self.data)
                data['attempts'][0]['wall_seconds'] = value
                with self.assertRaises(InvalidResult):
                    validate(data)
        for value in (True, -1, 1.5):
            self.data['attempts'][0]['output_tokens'] = value
            with self.assertRaises(InvalidResult):
                validate(self.data)

    def test_timeout_is_unsolved_and_usage_missing_is_unknown(self):
        row = self.data['attempts'][0]
        row['outcome'] = 'timeout'
        report = summarize(self.data)
        self.assertEqual(report['contestants']['demo-a']['matched_solved'], 0)
        for attempt in self.data['attempts']:
            attempt['input_tokens'] = 4
            attempt['output_tokens'] = 2
        report = summarize(self.data)
        self.assertEqual(report['contestants']['demo-a']['matched_input_tokens'], 8)
        self.data['attempts'][0]['input_tokens'] = None
        self.assertIsNone(summarize(self.data)['contestants']['demo-a']['matched_input_tokens'])

    def test_no_eligible_blocks_is_not_zero_percent(self):
        for row in self.data['attempts']:
            row['outcome'] = 'infrastructure_error'
        report = summarize(self.data)
        self.assertEqual(report['matched_blocks'], 0)
        self.assertIsNone(report['contestants']['demo-a']['matched_solve_rate'])

    def test_repeats_are_not_independent_tasks(self):
        self.data['repetitions'] = 2
        extra = copy.deepcopy(self.data['attempts'])
        for row in extra:
            row['repetition'] = 1
        self.data['attempts'].extend(extra)
        report = summarize(self.data)
        self.assertEqual(report['independent_tasks'], 3)
        self.assertEqual(report['planned_blocks'], 6)
        self.assertEqual(report['matched_blocks'], 4)

    def test_canonical_hash_independent_of_object_key_order(self):
        reordered = dict(reversed(list(self.data.items())))
        self.assertEqual(summarize(self.data)['result_sha256'], summarize(reordered)['result_sha256'])

    def test_json_duplicate_keys_rejected_and_cli_hides_private_values(self):
        # TemporaryDirectory uses the default OS temp location only for tiny JSON,
        # not builds, profiles, clones or proof artifacts.
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'result.json'
            path.write_text('{"schema_version":1,"schema_version":1,"secret":"private-value"}')
            with self.assertRaises(InvalidResult):
                load(path)
            result = subprocess.run([sys.executable, '-m', 'keel_arena', 'report', str(path)],
                                    cwd=ROOT, capture_output=True, text=True)
            self.assertEqual(result.returncode, 2)
            self.assertNotIn('private-value', result.stderr)
            self.assertNotIn(str(path), result.stderr)

    def test_cli_demo(self):
        result = subprocess.run([sys.executable, '-m', 'keel_arena', 'report',
                                 'examples/synthetic-results.json'],
                                cwd=ROOT, capture_output=True, text=True, check=True)
        report = json.loads(result.stdout)
        self.assertEqual(report['purpose'], 'demonstration')
        self.assertEqual(report['union_solved_blocks'], 2)


if __name__ == '__main__':
    unittest.main()
