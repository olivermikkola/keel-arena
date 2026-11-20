#!/usr/bin/env python3
"""Heuristic audit of Git-tracked public sources, without printing matched data."""

import re
import subprocess
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
ALLOWED_FILES = {
    ".gitignore", "AGENTS.md", "README.md", "LICENSE", "CONTRIBUTING.md",
    "SECURITY.md", "pyproject.toml", ".github/pull_request_template.md",
    "tasks/suites.json", "tasks/gauntlet/manifest.json",
}
ALLOWED_DIRS = {
    "keel_arena",
    "tests",
    "docs",
    "examples",
    "examples/synthetic-keel-mobile",
    "examples/synthetic-keel-mobile/base-run",
    "examples/synthetic-keel-mobile/adapted-run",
    "scripts",
    ".github/workflows",
    "tasks/repair",
}
ALLOWED_DIRS |= {
    f"tasks/repair/{task}{part}"
    for task in ("config-check", "csv-total")
    for part in ("", "/environment", "/environment/workspace", "/tests", "/solution")
}
GAUNTLET_TASKS = {
    "coding": ("cli-pipeline-fix", "terminal-log-indexer"),
    "tool-use": ("sqlite-query-repair", "api-contract-recovery"),
    "adversarial": ("injected-issue-triage", "misleading-hint-trap"),
    "agent-chains": ("release-readiness-chain", "incident-postmortem-chain"),
    "structured": ("invoice-normalization", "config-migration-schema"),
    "retrieval": ("chronological-policy-override", "cross-repo-dependency-trace"),
    "instruction": ("stacked-spec-brief", "code-review-patch-notes"),
}
ALLOWED_DIRS |= {
    f"tasks/gauntlet/{suite}/{task}{part}"
    for suite, names in GAUNTLET_TASKS.items()
    for task in names
    for part in (
        "",
        "/environment",
        "/environment/workspace",
        "/environment/workspace/changelogs",
        "/environment/workspace/manifests",
        "/environment/workspace/deploy",
        "/environment/workspace/checks",
        "/environment/workspace/incidents",
        "/environment/workspace/docs",
        "/environment/workspace/traces",
        "/tests",
        "/solution",
    )
}
PATTERNS = [
    # Values are never printed. Split pattern literals avoid self-matches.
    re.compile(r"(?:gh[pousr]_" + r"[A-Za-z0-9]{20,}|github_pat_" + r"[A-Za-z0-9_]{20,})"),
    re.compile(r"(?:sk-" + r"[A-Za-z0-9_-]{20,}|AKIA" + r"[A-Z0-9]{16})"),
    re.compile(r"-----BEGIN " + r"(?:RSA |OPENSSH |EC )?PRIVATE KEY-----"),
    re.compile(r"(?i)https?://[^\s/]+:[^\s/@]+@"),
    re.compile(r"/(?:home|Users)/" + r"[^\s/]+/"),
]


def inspect(path, content):
    relative = PurePosixPath(path)
    parent = relative.parent.as_posix()
    if path not in ALLOWED_FILES and parent not in ALLOWED_DIRS:
        return "path outside publication allowlist"
    allowed_suffixes = {"", ".py", ".md", ".json", ".toml", ".yml", ".sh", ".txt", ".csv", ".jsonl", ".ini", ".patch"}
    if path.startswith("tasks/gauntlet/"):
        allowed_suffixes |= {".env", ".log"}
    if path.startswith("examples/synthetic-keel-mobile/"):
        allowed_suffixes |= {".sha256", ".log"}
    if path in {"docs/overview-demo.svg", "docs/card-demo.svg"}:
        allowed_suffixes.add(".svg")
    if relative.suffix not in allowed_suffixes and path != '.gitignore':
        return "unreviewed file type"
    if len(content) > 256 * 1024:
        return "file exceeds public source size limit"
    try:
        text = content.decode('utf-8')
    except UnicodeDecodeError:
        return "binary or non-UTF-8 content"
    if any(pattern.search(text) for pattern in PATTERNS):
        return "possible secret or private location"
    return None


def main():
    paths = subprocess.check_output(['git', 'ls-files', '-z'], cwd=ROOT).decode().split('\0')
    failures = 0
    for path in filter(None, paths):
        mode = subprocess.check_output(['git', 'ls-files', '-s', '--', path], cwd=ROOT).split()[0]
        if mode not in (b'100644', b'100755'):
            reason = 'symlink, submodule or unexpected file mode'
        else:
            # Check working bytes and staged bytes: an unstaged edit must not hide
            # sensitive content already in the index.
            staged = subprocess.check_output(['git', 'show', ':' + path], cwd=ROOT)
            file = ROOT / path
            reason = inspect(path, staged)
            if not reason:
                if file.is_symlink():
                    reason = 'working file is a symlink'
                elif not file.is_file():
                    reason = 'tracked working file missing'
                else:
                    reason = inspect(path, file.read_bytes())
        if reason:
            failures += 1
            print(f'FAIL tracked file: {reason}')
    if failures:
        print(f'Publication audit failed: {failures} file(s). Values and paths withheld.')
        return 1
    print('Publication audit passed (tracked sources and index; heuristic only).')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
