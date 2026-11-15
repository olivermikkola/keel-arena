"""Protected controller. Never import candidate code into this process."""

import json
import os
import resource
import signal
import subprocess
import sys
import tempfile
from pathlib import Path

CASES = [({'workers': 1, 'label': 'app-1'}, {'ok': True}),
 ({'workers': 16, 'label': 'app-1'}, {'ok': True}),
 ({'workers': 4, 'label': 'app-1'}, {'ok': True}),
 ({'workers': True, 'label': 'app-1'}, {'ok': False}),
 ({'workers': False, 'label': 'app-1'}, {'ok': False}),
 ({'workers': 0, 'label': 'app-1'}, {'ok': False}),
 ({'workers': -1, 'label': 'app-1'}, {'ok': False}),
 ({'workers': 17, 'label': 'app-1'}, {'ok': False}),
 ({'workers': 1.0, 'label': 'app-1'}, {'ok': False}),
 ({'workers': '4', 'label': 'app-1'}, {'ok': False}),
 ({'workers': None, 'label': 'app-1'}, {'ok': False}),
 ({'workers': 2, 'label': 'a'}, {'ok': True}),
 ({'workers': 2, 'label': 'aaaaaaaaaaaa'}, {'ok': True}),
 ({'workers': 2, 'label': 'aaaaaaaaaaaaa'}, {'ok': False}),
 ({'workers': 2, 'label': ''}, {'ok': False}),
 ({'workers': 2, 'label': 'space name'}, {'ok': False}),
 ({'workers': 2, 'label': 'ää'}, {'ok': False}),
 ({'workers': 2, 'label': 'A_Z'}, {'ok': False}),
 ({'workers': 2, 'label': 'abc\n'}, {'ok': False}),
 ({}, {'ok': False}),
 ([], {'ok': False}),
 (None, {'ok': False}),
 ({'workers': 2, 'label': 'a', 'extra': 1}, {'ok': False})]


def limits():
    resource.setrlimit(resource.RLIMIT_CPU, (2, 2))
    resource.setrlimit(resource.RLIMIT_AS, (128 * 1024 * 1024, 128 * 1024 * 1024))
    resource.setrlimit(resource.RLIMIT_FSIZE, (1024 * 1024, 1024 * 1024))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))


def evaluate(candidate, isolate=True):
    candidate = Path(candidate)
    if candidate.is_symlink() or not candidate.is_file():
        return {'passed': 0, 'total': len(CASES)}
    if isolate and os.geteuid() != 0:
        raise RuntimeError('protected verification requires root to drop candidate privileges')
    passed = 0
    for value, expected in CASES:
        # A bounded file rather than PIPE avoids buffering arbitrary candidate output.
        with tempfile.TemporaryFile() as output:
            options = {'user': 65534, 'group': 65534, 'extra_groups': []} if isolate else {}
            process = subprocess.Popen([sys.executable, '-I', '-S', str(candidate)],
                                       stdin=subprocess.PIPE, stdout=output, stderr=subprocess.DEVNULL,
                                       cwd='/', env={'PATH': '/usr/bin:/bin', 'LANG': 'C.UTF-8'},
                                       start_new_session=True, preexec_fn=limits, **options)
            try:
                process.communicate(json.dumps(value).encode(), timeout=1)
                output.seek(0)
                raw = output.read(1024 * 1024 + 1)
                actual = json.loads(raw) if len(raw) <= 1024 * 1024 else None
                # JSON booleans compare equal to integers in Python: compare typed
                # canonical documents so a bogus `true` total cannot equal 1.
                if process.returncode == 0 and json.dumps(actual, sort_keys=True) == json.dumps(expected, sort_keys=True):
                    passed += 1
            except (subprocess.TimeoutExpired, ValueError, UnicodeError):
                pass
            finally:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                process.wait()
    return {'passed': passed, 'total': len(CASES)}


if __name__ == '__main__':
    if os.geteuid() != 0:
        raise SystemExit('protected verifier requires root')
    report = evaluate('/workspace/main.py')
    directory = Path('/logs/verifier')
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    (directory / 'checks.json').write_text(json.dumps(report) + '\n')
    (directory / 'reward.txt').write_text('1' if report['passed'] == report['total'] else '0')
