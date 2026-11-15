import copy
import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path

from keel_arena.results import InvalidResult
from keel_arena.trajectories import build_trajectory, export_trajectory

HAS_HARBOR = importlib.util.find_spec('harbor') is not None
if os.environ.get('ARENA_REQUIRE_HARBOR') and not HAS_HARBOR:
    raise ImportError('required Harbor SDK missing')


@unittest.skipUnless(HAS_HARBOR, 'optional harbor==0.26.0 not installed')
class TrajectoryTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / 'run').mkdir()
        initial = [{'role': 'system', 'content': 'Synthetic test harness.'},
                   {'role': 'user', 'content': 'Write a test file.'}]
        action = {'role': 'assistant', 'content': None, 'tool_calls': [{
            'id': 'call0', 'type': 'function', 'function': {'name': 'write_file',
            'arguments': '{"path":"file.txt","content":"example"}'}}]}
        receipt = {'role': 'tool', 'tool_call_id': 'call0', 'content': 'File written.'}
        self.records = [
            {'request': {'model': 'fixture', 'messages': initial},
             'response': {'choices': [{'message': action}],
                          'usage': {'prompt_tokens': 12, 'completion_tokens': 8}}},
            {'request': {'model': 'fixture', 'messages': initial + [action, receipt]},
             'response': {'choices': [{'message': {'role': 'assistant', 'content': 'Done.'}}],
                          'usage': {'prompt_tokens': 20, 'completion_tokens': 2}}},
        ]
        self.runtime = {'requests': 2, 'input_tokens': 32, 'output_tokens': 10,
                        'binary_sha256': '1' * 64, 'status': 'completed'}
        self.save()

    def save(self):
        (self.root / 'run/runtime.json').write_text(json.dumps(self.runtime))
        for index, record in enumerate(self.records, 1):
            (self.root / f'run/completion-{index}.json').write_text(json.dumps(record))

    def test_real_upstream_validation_and_exact_observation_join(self):
        from harbor.utils.trajectory_validator import TrajectoryValidator
        output = self.root / 'trajectory.json'
        report = export_trajectory(self.root, output)
        self.assertEqual(report['format'], 'ATIF-v1.8')
        self.assertEqual(report['steps'], 4)
        validator = TrajectoryValidator()
        self.assertTrue(validator.validate(output), validator.get_errors())
        trace = json.loads(output.read_text())
        action = trace['steps'][2]
        self.assertEqual(action['tool_calls'][0]['arguments']['path'], 'file.txt')
        self.assertEqual(action['observation']['results'][0]['source_call_id'], 'r1:call0')
        self.assertEqual(action['observation']['results'][0]['content'], 'File written.')
        self.assertEqual(output.stat().st_mode & 0o777, 0o600)
        self.assertFalse(trace['extra']['missing_replayed_observations'])
        with self.assertRaises(InvalidResult):
            export_trajectory(self.root, output)

    def test_context_rewrites_do_not_invent_or_misattribute_observations(self):
        self.records[1]['request']['messages'] = [{'role': 'system', 'content': 'Compacted context.'},
                                                 {'role': 'tool', 'tool_call_id': 'call0', 'content': 'Old receipt.'}]
        self.save()
        trace = build_trajectory(self.root)
        self.assertNotIn('observation', trace['steps'][2])
        self.assertEqual(trace['extra']['missing_replayed_observations'], ['r1:call0'])

    def test_incomplete_malformed_or_symlinked_ledgers_refused(self):
        (self.root / 'run/completion-2.json').unlink()
        with self.assertRaises(InvalidResult):
            build_trajectory(self.root)
        self.save()
        self.records[0]['response']['choices'][0]['message']['tool_calls'][0]['function']['arguments'] = '{bad-json'
        self.save()
        with self.assertRaises(ValueError):
            build_trajectory(self.root)
        source = self.root / 'run/completion-1.json'
        source.unlink()
        source.symlink_to(self.root / 'run/completion-2.json')
        with self.assertRaises(InvalidResult):
            build_trajectory(self.root)

    def test_native_records_hashed_and_unknown_usage_preserved(self):
        trace = build_trajectory(self.root)
        import hashlib
        expected = hashlib.sha256((self.root / 'run/completion-1.json').read_bytes()).hexdigest()
        self.assertEqual(trace['extra']['native_requests'][0]['sha256'], expected)
        self.runtime['input_tokens'] = None
        self.records[1]['response'].pop('usage')
        self.save()
        trace = build_trajectory(self.root)
        self.assertNotIn('total_prompt_tokens', trace['final_metrics'])
        self.assertNotIn('metrics', trace['steps'][-1])

    def test_scoped_ids_handle_reuse_in_later_rounds(self):
        action = copy.deepcopy(self.records[0]['response']['choices'][0]['message'])
        self.records[1]['response']['choices'][0]['message'] = action
        request = copy.deepcopy(self.records[1]['request'])
        request['messages'] += [action, {'role': 'tool', 'tool_call_id': 'call0', 'content': 'Second write.'}]
        self.records.append({'request': request, 'response': {'choices': [{'message': {'content': 'Done.'}}]}})
        self.runtime['requests'] = 3
        self.runtime['input_tokens'] = None
        self.runtime['output_tokens'] = None
        self.save()
        trace = build_trajectory(self.root)
        self.assertEqual(trace['steps'][2]['tool_calls'][0]['tool_call_id'], 'r1:call0')
        self.assertEqual(trace['steps'][3]['tool_calls'][0]['tool_call_id'], 'r2:call0')
        self.assertEqual(trace['steps'][3]['observation']['results'][0]['content'], 'Second write.')

    def test_usage_disagreement_is_not_silently_exported(self):
        self.runtime['output_tokens'] = 999
        self.save()
        with self.assertRaises(InvalidResult):
            build_trajectory(self.root)

    def test_stream_wire_reference_is_verified_before_timeline_export(self):
        import hashlib
        raw = b'data: [DONE]\n\n'
        (self.root / 'run/stream-1.sse').write_bytes(raw)
        self.records[0]['response']['arena_stream'] = {'file': 'stream-1.sse',
                                                     'sha256': hashlib.sha256(raw).hexdigest()}
        self.save()
        trace = build_trajectory(self.root)
        self.assertEqual(trace['extra']['native_requests'][0]['stream']['sha256'], hashlib.sha256(raw).hexdigest())
        (self.root / 'run/stream-1.sse').write_bytes(b'changed wire evidence')
        with self.assertRaises(InvalidResult):
            build_trajectory(self.root)
