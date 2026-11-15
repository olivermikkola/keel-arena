import io
import json
import tempfile
import unittest
from pathlib import Path

from keel_arena.runtime import ProviderStreamError, read_completion


class Response(io.BytesIO):
    headers = {'Content-Type': 'text/event-stream; charset=utf-8'}


class StreamingTest(unittest.TestCase):
    def collect(self, chunks, done=True):
        raw = b': heartbeat\n\n' + b''.join(b'data: ' + json.dumps(chunk).encode() + b'\n\n' for chunk in chunks)
        if done:
            raw += b'data: [DONE]\n\n'
        with tempfile.TemporaryDirectory() as directory:
            return read_completion(Response(raw), Path(directory), 1)

    def test_text_reasoning_tool_fragments_and_usage_only_event(self):
        output = self.collect([
            {'id': 'reply', 'choices': [{'index': 0, 'delta': {'content': 'Hi ', 'reasoning_content': 'Check. ',
                'tool_calls': [{'index': 0, 'id': 'call0', 'function': {'name': 'write_', 'arguments': '{"x":'}}]}}]},
            {'choices': [{'index': 0, 'delta': {'content': 'there', 'tool_calls': [
                {'index': 0, 'function': {'name': 'file', 'arguments': '1}'}}]}, 'finish_reason': 'tool_calls'}]},
            {'choices': [], 'usage': {'prompt_tokens': 12, 'completion_tokens': 6}},
        ])
        message = output['choices'][0]['message']
        self.assertEqual(message['content'], 'Hi there')
        self.assertEqual(message['reasoning_content'], 'Check. ')
        self.assertEqual(message['tool_calls'][0]['function'], {'name': 'write_file', 'arguments': '{"x":1}'})
        self.assertEqual(output['usage']['prompt_tokens'], 12)
        self.assertEqual(len(output['arena_stream']['sha256']), 64)

    def test_partial_or_error_streams_never_become_complete_answers(self):
        with self.assertRaises(ValueError):
            self.collect([{'choices': [{'delta': {'content': 'partial'}}]}], done=False)
        with self.assertRaises(ProviderStreamError):
            self.collect([{'error': {'code': 'context_length_exceeded'}}])

    def test_out_of_order_parallel_tool_indices_preserve_identity(self):
        output = self.collect([{'choices': [{'delta': {'tool_calls': [
            {'index': 1, 'id': 'b', 'function': {'name': 'read_file', 'arguments': '{}'}},
            {'index': 0, 'id': 'a', 'function': {'name': 'write_file', 'arguments': '{}'}},
        ]}, 'finish_reason': 'tool_calls'}]}])
        self.assertEqual([t['id'] for t in output['choices'][0]['message']['tool_calls']], ['a', 'b'])

    def test_stream_evidence_limit_is_enforced(self):
        from keel_arena.runtime import LIMIT
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(ValueError):
                read_completion(Response(b'data: ' + b'x' * LIMIT), Path(directory), 1)
            self.assertLessEqual((Path(directory) / 'stream-1.sse').stat().st_size, LIMIT)
