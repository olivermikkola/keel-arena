"""Private ATIF export tied to exact native request/response evidence."""

import hashlib
import json
import os
from pathlib import Path

from .harbor_import import canonical_hash, read_bytes, read_json
from .results import integer, require


def build_trajectory(agent_directory):
    """Convert a complete recorded text-only request ledger; invent no observations."""
    root = Path(agent_directory)
    require(root.is_dir() and not root.is_symlink(), 'invalid agent evidence directory')
    runtime = read_json(read_bytes(root, 'run/runtime.json'))
    count = runtime.get('requests')
    require(integer(count, 1) and count <= 10000, 'no complete request ledger')
    paths = list((root / 'run').glob('completion-*.json'))
    require(len(paths) == count, 'request ledger is incomplete')
    records, references = [], []
    for index in range(1, count + 1):
        relative = f'run/completion-{index}.json'
        raw = read_bytes(root, relative)
        record = read_json(raw)
        require(isinstance(record, dict) and set(record) == {'request', 'response'}, 'invalid completion record')
        require(isinstance(record['request'], dict) and isinstance(record['request'].get('messages'), list),
                'missing request context')
        references.append({'file': relative, 'sha256': hashlib.sha256(raw).hexdigest(),
                           'request_sha256': canonical_hash(record['request'])})
        stream = record['response'].get('arena_stream') if isinstance(record['response'], dict) else None
        if stream is not None:
            require(isinstance(stream, dict) and isinstance(stream.get('file'), str) and
                    stream['file'] == f'stream-{index}.sse', 'invalid native stream reference')
            raw_stream = read_bytes(root, 'run/' + stream['file'])
            require(hashlib.sha256(raw_stream).hexdigest() == stream.get('sha256'), 'native stream digest mismatch')
            references[-1]['stream'] = stream
        records.append(record)
    steps = []
    for message in records[0]['request']['messages']:
        require(isinstance(message, dict), 'invalid initial context message')
        role = message.get('role')
        require(role in ('system', 'developer', 'user') and isinstance(message.get('content'), str),
                'fresh text-only initial context required')
        steps.append({'step_id': len(steps) + 1, 'source': 'user' if role == 'user' else 'system',
                      'message': message['content'], 'extra': {'native_role': role}})
    require(steps, 'initial context required')
    model = records[0]['request'].get('model')
    require(isinstance(model, str) and model, 'model identity missing')
    missing_observations = []
    for index, record in enumerate(records, 1):
        require(record['request'].get('model') == model, 'mixed-model ledger unsupported')
        response = record['response']
        require(isinstance(response, dict) and isinstance(response.get('choices'), list)
                and len(response['choices']) == 1, 'one completion choice required')
        require(isinstance(response['choices'][0], dict), 'invalid completion choice')
        message = response['choices'][0].get('message')
        require(isinstance(message, dict), 'assistant message missing')
        content = message.get('content')
        require(content is None or isinstance(content, str), 'multimodal output not supported')
        step = {'step_id': len(steps) + 1, 'source': 'agent', 'model_name': model,
                'message': content or '', 'llm_call_count': 1,
                'extra': {'native_request': references[index - 1]}}
        if message.get('reasoning_content') is not None:
            require(isinstance(message['reasoning_content'], str), 'invalid reasoning content')
            step['reasoning_content'] = message['reasoning_content']
        calls = message.get('tool_calls') or []
        require(isinstance(calls, list), 'invalid tool calls')
        native_ids, converted = set(), []
        for call in calls:
            require(isinstance(call, dict) and isinstance(call.get('id'), str) and call['id'],
                    'native tool-call ID required')
            native_id = call['id']
            require(native_id not in native_ids, 'duplicate native call ID within completion')
            native_ids.add(native_id)
            function = call.get('function')
            require(isinstance(function, dict) and isinstance(function.get('name'), str), 'function required')
            arguments = function.get('arguments')
            if isinstance(arguments, str):
                arguments = read_json(arguments.encode())
            require(isinstance(arguments, dict), 'malformed native arguments retained only in native evidence')
            converted.append({'tool_call_id': f'r{index}:{native_id}', 'function_name': function['name'],
                              'arguments': arguments, 'extra': {'native_tool_call_id': native_id}})
        if converted:
            step['tool_calls'] = converted
            observations = []
            # A tool result is an observation only if it really appeared in the
            # next request. Never synthesize success from the call arguments.
            next_messages = records[index]['request']['messages'] if index < len(records) else []
            previous_messages = record['request']['messages']
            if next_messages[:len(previous_messages)] == previous_messages:
                next_messages = next_messages[len(previous_messages):]
            else:
                # A rewritten context can contain an old receipt with a reused
                # call ID. Missing is safer than attributing that stale result.
                next_messages = []
            for call in converted:
                native_id = call['extra']['native_tool_call_id']
                matches = [m for m in next_messages if isinstance(m, dict) and m.get('role') == 'tool' and m.get('tool_call_id') == native_id]
                require(len(matches) <= 1, 'ambiguous replayed observation')
                if matches:
                    require(isinstance(matches[0].get('content'), str), 'text-only observation required')
                    observations.append({'source_call_id': call['tool_call_id'], 'content': matches[0]['content'],
                                         'extra': {'source': 'next-native-request'}})
                else:
                    missing_observations.append(call['tool_call_id'])
            if observations:
                step['observation'] = {'results': observations}
        usage = response.get('usage') or {}
        require(isinstance(usage, dict), 'invalid usage')
        metrics = {}
        for source, target in (('prompt_tokens', 'prompt_tokens'), ('completion_tokens', 'completion_tokens')):
            value = usage.get(source)
            require(value is None or integer(value), 'invalid token usage')
            if value is not None:
                metrics[target] = value
        if metrics:
            step['metrics'] = metrics
        steps.append(step)
    totals = {}
    for key, target in (('input_tokens', 'total_prompt_tokens'), ('output_tokens', 'total_completion_tokens')):
        value = runtime.get(key)
        require(value is None or integer(value), 'invalid aggregate usage')
        totals[target] = value
    for key, target in (('prompt_tokens', 'total_prompt_tokens'), ('completion_tokens', 'total_completion_tokens')):
        observed = [(record['response'].get('usage') or {}).get(key) for record in records]
        if totals[target] is not None and all(value is not None for value in observed):
            require(sum(observed) == totals[target], 'aggregate usage disagrees with native ledger')
    trajectory = {
        'schema_version': 'ATIF-v1.8',
        'agent': {'name': 'keel-arena', 'version': runtime.get('binary_sha256'), 'model_name': model,
                  'tool_definitions': records[0]['request'].get('tools')},
        'steps': steps, 'final_metrics': {**totals, 'total_steps': len(steps)},
        'notes': 'Execution timeline, not a tokenizer-ready training sequence. Native requests preserve context rewrites.',
        'extra': {'arena_runtime_status': runtime.get('status'), 'native_requests': references,
                  'missing_replayed_observations': missing_observations,
                  'raw_context_authority': 'native-request-records'},
    }
    # Use the pinned upstream schema and validator rather than a permissive
    # imitation of ATIF. Optional SDK is loaded only for explicit export.
    from importlib.metadata import version
    require(version('harbor') == '0.26.0', 'unsupported ATIF SDK')
    from harbor.models.trajectories import Trajectory
    return Trajectory.model_validate(trajectory).to_json_dict()


def export_trajectory(agent_directory, output):
    trajectory = build_trajectory(agent_directory)
    raw = (json.dumps(trajectory, sort_keys=True, indent=2, allow_nan=False) + '\n').encode()
    require(len(raw) <= 16 * 1024 * 1024, 'trajectory exceeds export limit; native evidence retained')
    output = Path(output)
    require(not output.exists() and not output.is_symlink(), 'export destination must be new')
    with open(output, 'xb', opener=lambda p, flags: os.open(p, flags, 0o600)) as target:
        target.write(raw)
    return {'exported': True, 'format': 'ATIF-v1.8', 'steps': len(trajectory['steps']),
            'sha256': hashlib.sha256(raw).hexdigest()}
