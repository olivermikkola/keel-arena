import copy
import itertools
import json
import unittest
from pathlib import Path

from keel_arena.results import InvalidResult, estimate_pass, summarize

ROOT = Path(__file__).resolve().parents[1]


class MetricsTest(unittest.TestCase):
    def test_pass_estimate_matches_exhaustive_sampling_not_another_formula(self):
        for n in range(1, 9):
            for correct in range(n + 1):
                for k in range(1, n + 1):
                    combinations = list(itertools.combinations(range(n), k))
                    actual = sum(any(index < correct for index in sample) for sample in combinations) / len(combinations)
                    self.assertAlmostEqual(estimate_pass(n, correct, k), actual)

    def test_undefined_k_and_invalid_counts_are_refused(self):
        for values in ((0, 0, 1), (2, 3, 1), (2, 1, 3), (True, 0, 1), (2, 1, 0)):
            with self.assertRaises(InvalidResult):
                estimate_pass(*values)
        self.assertTrue(0 < estimate_pass(100000, 1, 1) < .001)
        self.assertEqual(estimate_pass(100000, 100000, 100000), 1)

    def data(self):
        data = json.loads((ROOT / 'examples/synthetic-results.json').read_text())
        data['repetitions'] = 3
        original = data['attempts'][:]
        data['attempts'] = []
        for rep in range(3):
            for row in original:
                item = copy.deepcopy(row)
                item['repetition'] = rep
                item['outcome'] = 'unsolved'
                item['verifier_result_sha256'] = 'a' * 64
                if item['task'] == 'toy-repair' and rep > 0:
                    item['outcome'] = 'infrastructure_error'
                elif item['task'] == 'toy-repair' and item['contestant'] == 'demo-a':
                    item['outcome'] = 'solved'
                data['attempts'].append(item)
        return data

    def test_equal_task_weight_and_explicit_pass_k_cohorts(self):
        data = self.data()
        report = summarize(data, pass_k=[1, 2, 4])
        result = report['contestants']['demo-a']
        self.assertAlmostEqual(result['matched_solve_rate'], 1 / 7)
        self.assertAlmostEqual(result['matched_task_mean_solve_rate'], 1 / 3)
        self.assertEqual(report['per_task']['toy-repair']['excluded_repetitions'], [1, 2])
        self.assertEqual(report['pass_at_k']['1']['eligible_task_ids'], ['toy-edit', 'toy-git', 'toy-repair'])
        self.assertEqual(report['pass_at_k']['2']['eligible_task_ids'], ['toy-edit', 'toy-git'])
        self.assertIsNone(report['pass_at_k']['4']['contestants']['demo-a'])
        self.assertEqual(report['paired_task_differences'][0]['per_task_difference']['toy-repair'], 1)
        self.assertAlmostEqual(report['paired_task_differences'][0]['mean_difference'], 1 / 3)

    def test_timeout_counts_as_failure_and_no_eligible_cohort_is_unknown(self):
        data = self.data()
        for row in data['attempts']:
            row['outcome'] = 'timeout'
        report = summarize(data)
        self.assertEqual(report['pass_at_k']['2']['contestants']['demo-a'], 0)
        for row in data['attempts']:
            row['outcome'] = 'infrastructure_error'
        report = summarize(data)
        self.assertEqual(report['tasks_with_matched_attempts'], 0)
        self.assertIsNone(report['contestants']['demo-a']['matched_task_mean_solve_rate'])
        self.assertIsNone(report['pass_at_k']['1']['contestants']['demo-a'])

    def test_pass_k_selection_is_bounded_and_validated(self):
        for ks in ([], [0], [False], list(range(1, 18)), [100001]):
            with self.assertRaises(InvalidResult):
                summarize(self.data(), pass_k=ks)

    def test_cli_markdown_retains_purpose_coverage_and_unknown_usage(self):
        import subprocess, sys
        result = subprocess.run([sys.executable, '-m', 'keel_arena', 'report',
                                 'examples/synthetic-results.json', '--pass-k', '1,2', '--format', 'markdown'],
                                cwd=ROOT, capture_output=True, text=True, check=True)
        self.assertIn('**demonstration**', result.stdout)
        self.assertIn('matched blocks: 2/3', result.stdout)
        self.assertIn('| demo-a | 1 / 2 | 50.0% | unknown | unknown |', result.stdout)
        self.assertIn('| 2 | 0 | unknown | unknown |', result.stdout)
