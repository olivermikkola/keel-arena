"""Private frozen studies using Harbor's existing trial lifecycle, serially."""

import asyncio
import contextlib
import hashlib
import json
import os
import uuid
from pathlib import Path

from .harbor_import import HARBOR_VERSION, canonical_hash, import_binding, import_trials, read_json, validate_manifest
from .results import fields, identifier, integer, require, summarize
from .runtime import validate_config


def _sdk():
    from importlib.metadata import version
    require(version('harbor') == HARBOR_VERSION, 'unsupported Harbor SDK')
    from harbor.models.task.task import Task
    from harbor.models.trial.config import TrialConfig
    from harbor.trial.trial import Trial
    return Task, TrialConfig, Trial


def _file_hash(path):
    with Path(path).open('rb') as source:
        return hashlib.file_digest(source, 'sha256').hexdigest()


def _code_hashes():
    return {name: _file_hash(Path(__file__).with_name(name))
            for name in ('study.py', 'runtime.py', 'harbor_agent.py', 'harbor_import.py', 'results.py')}


def _tree(path, file_filter=None):
    root = Path(path)
    files = {}
    for source in sorted(root.rglob('*')):
        if file_filter and file_filter.is_excluded(source):
            continue
        require(not source.is_symlink(), 'task symlinks are not supported')
        if source.is_file():
            files[source.relative_to(root).as_posix()] = {
                'sha256': _file_hash(source), 'mode': source.stat().st_mode & 0o777}
    require(files, 'empty task content')
    return canonical_hash(files)


def _write(path, data, replace=False):
    path = Path(path)
    import uuid
    target = path.with_name(path.name + '.' + uuid.uuid4().hex + '.pending') if replace else path
    with open(target, 'x', opener=lambda p, flags: os.open(p, flags, 0o600)) as file:
        json.dump(data, file, sort_keys=True, indent=2, allow_nan=False)
        file.write('\n')
        file.flush()
        os.fsync(file.fileno())
    if replace:
        target.replace(path)


def read_document(path):
    with Path(path).open('rb') as source:
        raw = source.read(16 * 1024 * 1024 + 1)
    require(len(raw) <= 16 * 1024 * 1024, 'study document exceeds 16 MiB')
    return read_json(raw)


def freeze(settings, output):
    """Resolve exact configs and sources without creating a trial or model call."""
    Task, TrialConfig, _ = _sdk()
    fields(settings, 'schema_version purpose split binary_path binary_sha256 tasks contestants '
                     'repetitions budget sampling environment thermal_limit_c', 'study')
    require(type(settings['schema_version']) is int and settings['schema_version'] == 1,
            'unsupported study schema')
    fields(settings['budget'], 'max_steps max_output_tokens timeout_seconds', 'budget')
    fields(settings['sampling'], 'temperature top_p seed thinking context_tokens', 'sampling')
    fields(settings['environment'], 'type allow_agent_hosts', 'environment')
    require(settings['environment']['type'] == 'docker', 'only explicit local Docker execution supported')
    hosts = settings['environment']['allow_agent_hosts']
    require(isinstance(hosts, list) and all(isinstance(h, str) and h for h in hosts), 'invalid allowed hosts')
    limit = settings['thermal_limit_c']
    require(limit is None or (integer(limit, 1) and limit <= 68), 'invalid thermal guard')
    binary = Path(settings['binary_path']).absolute()
    require(binary.is_file() and not binary.is_symlink(), 'invalid local binary')
    require(_file_hash(binary) == settings['binary_sha256'], 'binary digest mismatch')
    output = Path(output).absolute()
    require(not output.exists(), 'study output must be new')
    require(isinstance(settings['tasks'], dict) and settings['tasks'], 'tasks required')
    require(isinstance(settings['contestants'], dict) and settings['contestants'], 'contestants required')
    task_sources, tasks, workspaces = {}, {}, {}
    for name, path in settings['tasks'].items():
        require(identifier(name) and isinstance(path, str), 'invalid task identity')
        source = Path(path).absolute()
        require(source.is_dir() and not source.is_symlink(), 'invalid task source')
        task = Task(source)
        require(task.name == name and not task.has_steps, 'single-step task name must match study key')
        from harbor.models.task.verifier_mode import resolve_task_verifier_mode
        require(resolve_task_verifier_mode(task.config).value == 'separate', 'separate verifier required')
        workspaces[name] = task.config.environment.workdir
        snapshot = _tree(source, task.file_filter)
        verifier = _tree(task.paths.tests_dir, task.file_filter)
        task_sources[name] = {'path': str(source), 'snapshot_sha256': snapshot,
                              'verifier_sha256': verifier, 'task_checksum': task.checksum}
        tasks[name] = {'snapshot_sha256': snapshot, 'verifier_sha256': verifier, 'split': settings['split']}
    contestants = {}
    for name, contestant in settings['contestants'].items():
        require(identifier(name), 'invalid contestant identity')
        fields(contestant, 'model base_url model_revision_sha256 quantization api_key_env', 'contestant')
        key = contestant['api_key_env']
        if key is not None:
            import re
            require(isinstance(key, str) and re.fullmatch(r'[A-Z_][A-Z0-9_]{0,95}', key),
                    'API key must be an environment-variable name')
        validate_config(dict(binary=str(binary), binary_sha256=settings['binary_sha256'],
                             root='/workspace', home='/installed-agent/arena-home', logs='/logs/agent/run',
                             model=contestant['model'], base_url=contestant['base_url'],
                             max_model_requests=settings['budget']['max_steps'],
                             max_output_tokens=settings['budget']['max_output_tokens'],
                             timeout_seconds=settings['budget']['timeout_seconds'], **settings['sampling']))
        contestants[name] = {k: contestant[k] for k in ('model_revision_sha256', 'quantization')}
    plan = {'schema_version': 1, 'purpose': settings['purpose'], 'tasks': tasks,
            'contestants': contestants, 'repetitions': settings['repetitions'],
            'protocol': {'harness_revision': settings['binary_sha256'],
                         'environment_sha256': canonical_hash({'backend': HARBOR_VERSION,
                             'environment': settings['environment'], 'sources': task_sources,
                             'thermal_limit_c': limit, 'order': 'serial-rotating-v1',
                             'code': _code_hashes()}),
                         'sampling_sha256': canonical_hash({'policy': settings['sampling'], 'seed_schedule': 'base-plus-repetition'}),
                         'budget': settings['budget']}}
    from .results import validate_plan
    validate_plan(plan)
    bindings, configs = [], {}
    run_prefix = 'arena-' + uuid.uuid4().hex[:16]
    names = sorted(contestants)
    block = 0
    # Rotate model order per task/repetition block to reduce order bias.
    for repetition in range(settings['repetitions']):
        for name in sorted(tasks):
            rotation = block % len(names)
            for contestant_name in names[rotation:] + names[:rotation]:
                contestant = settings['contestants'][contestant_name]
                cell = f'{run_prefix}-{len(bindings):06d}'
                config = TrialConfig(
                    task={'path': task_sources[name]['path']}, trial_name=cell,
                    trials_dir=output / 'trials',
                    agent={'import_path': 'keel_arena.harbor_agent:KeelAgent',
                           'model_name': contestant['model'], 'base_url': contestant['base_url'],
                           'model_api_key_name': contestant['api_key_env'] or 'ARENA_ANONYMOUS_API_KEY',
                           'env': {'ARENA_ANONYMOUS_API_KEY': ''} if contestant['api_key_env'] is None else {},
                           'extra_allowed_hosts': hosts,
                           'override_timeout_sec': settings['budget']['timeout_seconds'] + 15,
                           'kwargs': {'workspace': workspaces[name], 'binary_path': str(binary), 'binary_sha256': settings['binary_sha256'],
                                      'max_model_requests': settings['budget']['max_steps'],
                                      'max_output_tokens': settings['budget']['max_output_tokens'],
                                      'timeout_seconds': settings['budget']['timeout_seconds'],
                                      **dict(settings['sampling'], seed=settings['sampling']['seed'] + repetition)}},
                    environment={'type': 'docker'}, verifier={'disable': False})
                serialized = config.model_dump(mode='json')
                configs[cell] = serialized
                bindings.append({'task': name, 'contestant': contestant_name, 'repetition': repetition,
                                 'directory': cell, 'task_checksum': task_sources[name]['task_checksum'],
                                 'config_sha256': canonical_hash(serialized)})
            block += 1
    manifest = {'schema_version': 1, 'harbor_version': HARBOR_VERSION, 'reward_metric': 'reward',
                'plan': plan, 'trials': bindings}
    validate_manifest(manifest)
    frozen = {'schema_version': 1, 'manifest': manifest, 'configs': configs, 'sources': task_sources,
              'binary': {'path': str(binary), 'sha256': settings['binary_sha256']},
              'code': _code_hashes(), 'thermal_limit_c': limit,
              'settings_sha256': canonical_hash(settings), 'output': str(output)}
    output.mkdir(mode=0o700, parents=True)
    _write(output / 'frozen.json', frozen)
    _write(output / 'receipt.json', {'frozen_sha256': canonical_hash(frozen)})
    _write(output / 'state.json', {'status': 'frozen', 'completed': 0})
    return {'frozen': True, 'planned_attempts': len(bindings), 'plan_sha256': canonical_hash(plan)}


def _temperature():
    values = []
    for device in Path('/sys/class/hwmon').glob('hwmon*'):
        for label in device.glob('temp*_label'):
            if label.read_text().strip() in ('Tctl', 'Package id 0'):
                values.append(int(label.with_name(label.name.replace('_label', '_input')).read_text()) / 1000)
    require(values, 'no supported CPU temperature sensor; choose thermal policy explicitly')
    return max(values)


def _verify_sources(frozen):
    Task, _, _ = _sdk()
    require(_code_hashes() == frozen['code'], 'Arena implementation changed since freeze')
    require(_file_hash(frozen['binary']['path']) == frozen['binary']['sha256'], 'binary changed since freeze')
    for source in frozen['sources'].values():
        task = Task(source['path'])
        require(_tree(task.task_dir, task.file_filter) == source['snapshot_sha256'], 'task changed since freeze')
        require(_tree(task.paths.tests_dir, task.file_filter) == source['verifier_sha256'], 'verifier changed since freeze')


async def _cancel_and_drain(task):
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task
    # Harbor shields separate-verifier stop(), so Trial.run() can finish its
    # cancellation before that child cleanup finishes. Do not let asyncio.run
    # cancel it at shutdown and leave a sidecar alive.
    pending = []
    for other in asyncio.all_tasks():
        if other is asyncio.current_task() or other.done():
            continue
        code = getattr(other.get_coro(), 'cr_code', None)
        if code and code.co_name == 'stop' and '/harbor/environments/' in code.co_filename:
            pending.append(other)
    if pending:
        await asyncio.gather(*pending)


async def _guarded_trial(trial, limit):
    task = asyncio.create_task(trial.run())
    try:
        while not task.done():
            if limit is not None and _temperature() >= limit:
                await _cancel_and_drain(task)
                return False
            await asyncio.wait({task}, timeout=.25)
        await task
        return True
    finally:
        if not task.done():
            await _cancel_and_drain(task)


async def execute(output, resume=False):
    """Execute a trusted frozen study. No implicit retries or replacement attempts."""
    import fcntl
    output = Path(output).absolute()
    require(output.is_dir() and not output.is_symlink(), 'invalid study directory')
    frozen = read_document(output / 'frozen.json')
    require(canonical_hash(frozen) == read_document(output / 'receipt.json')['frozen_sha256'], 'frozen study changed')
    require(frozen['schema_version'] == 1 and frozen['output'] == str(output), 'study moved or unsupported')
    manifest = validate_manifest(frozen['manifest'])
    _, TrialConfig, Trial = _sdk()
    with (output / '.execution.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError('another process is executing this study') from None
        state = read_document(output / 'state.json')
        require(resume or state['status'] == 'frozen', 'study already started; explicit resume required')
        _verify_sources(frozen)
        completed = 0
        for binding in manifest['trials']:
            cell = binding['directory']
            require(identifier(cell), 'invalid frozen cell')
            config_data = frozen['configs'][cell]
            require(canonical_hash(config_data) == binding['config_sha256'], 'frozen config mismatch')
            config = TrialConfig.model_validate(config_data)
            key_name = config.agent.model_api_key_name
            require(key_name == 'ARENA_ANONYMOUS_API_KEY' or (key_name and os.environ.get(key_name)),
                    'selected credential environment variable is missing')
            require(config.trial_name == cell and config.trials_dir.absolute() == output / 'trials',
                    'trial output escaped frozen study')
            directory = output / 'trials' / cell
            if directory.exists():
                require(resume, 'existing attempt requires explicit resume')
                import_binding(binding, output / 'trials', manifest['reward_metric'])
                completed += 1
                continue
            _verify_sources(frozen)
            limit = frozen['thermal_limit_c']
            if limit is not None and _temperature() >= limit:
                _write(output / 'state.json', {'status': 'thermal_stop', 'completed': completed}, replace=True)
                return {'status': 'thermal_stop', 'completed': completed, 'planned': len(manifest['trials'])}
            _write(output / 'state.json', {'status': 'running', 'completed': completed}, replace=True)
            trial = await Trial.create(config)
            require(canonical_hash(trial.config.model_dump(mode='json')) == binding['config_sha256'],
                    'backend changed frozen config')
            cool = await _guarded_trial(trial, limit)
            import_binding(binding, output / 'trials', manifest['reward_metric'])
            completed += 1
            _write(output / 'state.json', {'status': 'running' if cool else 'thermal_stop',
                                          'completed': completed}, replace=True)
            if not cool:
                return {'status': 'thermal_stop', 'completed': completed, 'planned': len(manifest['trials'])}
        result = import_trials(manifest, output / 'trials')
        report = summarize(result)
        for filename, value in (('results.json', result), ('report.json', report)):
            _write(output / filename, value, replace=True)
        _write(output / 'state.json', {'status': 'completed', 'completed': completed}, replace=True)
        return report
