"""One-command suite discovery and study initialization (stdlib only)."""

import hashlib
import json
import os
import shutil
import urllib.parse
from pathlib import Path

from .edge import detect_hardware, probe_server
from .results import SUITES, identifier, integer, require

def _file_sha256(path):
    with Path(path).open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def _resolve_tasks_root(tasks_root=None):
    if tasks_root is not None:
        return Path(tasks_root)
    checkout = Path(__file__).resolve().parents[1] / "tasks"
    if (checkout / "suites.json").is_file():
        return checkout
    cwd_tasks = Path.cwd() / "tasks"
    if (cwd_tasks / "suites.json").is_file():
        return cwd_tasks
    return checkout


def discover_suites(tasks_root=None):
    """Return available suites and tasks from tasks/suites.json."""
    root = _resolve_tasks_root(tasks_root)
    index_path = root / "suites.json"
    require(index_path.is_file(), "tasks/suites.json index not found")
    data = json.loads(index_path.read_text(encoding="utf-8"))
    require(isinstance(data, dict) and isinstance(data.get("tasks"), dict), "invalid suites.json")
    tasks = {}
    for task_id, meta in data["tasks"].items():
        require(identifier(task_id) and isinstance(meta, dict), "invalid task entry in suites.json")
        suite = meta.get("suite")
        require(suite in SUITES, f"invalid suite {suite} for {task_id}")
        rel = meta.get("path")
        require(isinstance(rel, str) and rel, "task path required")
        task_dir = (root / rel).resolve()
        tasks[task_id] = {
            "id": task_id,
            "suite": suite,
            "judge_mode": meta.get("judge_mode", "deterministic"),
            "path": str(task_dir),
            "summary": meta.get("summary", ""),
        }
    return {"schema_version": data.get("schema_version", 1), "tasks": tasks}


def select_tasks(suite_filter="all", tasks_root=None):
    """Select tasks matching 'all', 'gauntlet', 'repair', or comma-separated suite names."""
    index = discover_suites(tasks_root)
    tasks = index["tasks"]
    if suite_filter == "all":
        selected = tasks
    elif suite_filter == "gauntlet":
        selected = {k: v for k, v in tasks.items() if v["suite"] != "repair"}
    elif suite_filter == "repair":
        selected = {k: v for k, v in tasks.items() if v["suite"] == "repair"}
    else:
        wanted = {s.strip() for s in suite_filter.split(",") if s.strip()}
        require(wanted and wanted.issubset(set(SUITES)), "unknown suite in selection")
        selected = {k: v for k, v in tasks.items() if v["suite"] in wanted}
    require(selected, "no tasks matched selection")
    return selected


def parse_contestant_spec(spec):
    """Parse NAME=MODEL@BASE_URL[|QUANT|HARNESS|API_KEY_ENV]."""
    require(isinstance(spec, str) and "=" in spec and "@" in spec,
            "contestant spec must look like name=model@http://host:port/v1[|quant|harness|API_KEY_ENV]")
    name, rest = spec.split("=", 1)
    require(identifier(name), "invalid contestant name")
    model, tail = rest.split("@", 1)
    require(bool(model), "contestant model required")
    parts = tail.split("|")
    base_url = parts[0]
    url = urllib.parse.urlsplit(base_url)
    require(url.scheme in ("http", "https") and bool(url.hostname), "invalid contestant base_url")
    quant = parts[1] if len(parts) > 1 and parts[1] else "none"
    harness = parts[2] if len(parts) > 2 and parts[2] else "keel"
    api_key_env = parts[3] if len(parts) > 3 and parts[3] else None
    require(identifier(quant) and identifier(harness), "invalid quantization or harness")
    return name, {
        "model": model,
        "base_url": base_url,
        "quantization": quant,
        "harness": harness,
        "api_key_env": api_key_env,
    }


def _find_keel_binary(binary_path=None):
    if binary_path:
        path = Path(binary_path).expanduser().absolute()
        require(path.is_file() and not path.is_symlink(), "invalid keel binary_path")
        return path
    found = shutil.which("keel")
    if found:
        return Path(found).resolve()
    local = Path.home() / ".local/bin/keel"
    if local.is_file():
        return local.resolve()
    raise ValueError("keel binary not found; pass --binary PATH")


def init_study(
    *,
    contestant_specs,
    out_path,
    suite="gauntlet",
    binary_path=None,
    repetitions=1,
    split="development",
    purpose="benchmark",
    max_steps=12,
    max_output_tokens=4096,
    timeout_seconds=300,
    context_tokens=16384,
    temperature=0.0,
    top_p=1.0,
    seed=0,
    thinking=None,
    thermal_limit_c=65,
    probe_edge=False,
    tasks_root=None,
):
    """Build a ready-to-freeze study configuration with auto-hashed binary & hardware metadata."""
    require(contestant_specs, "at least one --contestant is required")
    require(integer(repetitions, 1), "repetitions must be positive")
    binary = _find_keel_binary(binary_path)
    binary_sha = _file_sha256(binary)
    selected_tasks = select_tasks(suite, tasks_root=tasks_root)

    contestants = {}
    hosts = set()
    for spec in contestant_specs:
        name, entry = parse_contestant_spec(spec)
        require(name not in contestants, "duplicate contestant name")
        host = urllib.parse.urlsplit(entry["base_url"]).hostname
        if host:
            hosts.add(host)
        manifest_basis = {
            "model": entry["model"],
            "quantization": entry["quantization"],
            "harness": entry["harness"],
        }
        if probe_edge:
            api_key = os.environ.get(entry["api_key_env"]) if entry["api_key_env"] else None
            probe = probe_server(entry["base_url"], entry["model"], api_key=api_key, streams=(1, 2))
            entry["edge_profile"] = probe["edge_profile"]
            manifest_basis["profile_sha256"] = probe["profile_sha256"]
        entry["model_revision_sha256"] = hashlib.sha256(
            json.dumps(manifest_basis, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        contestants[name] = entry

    doc = {
        "schema_version": 2,
        "purpose": purpose,
        "split": split,
        "binary_path": str(binary),
        "binary_sha256": binary_sha,
        "tasks": {tid: meta["path"] for tid, meta in selected_tasks.items()},
        "task_metadata": {
            tid: {"suite": meta["suite"], "judge_mode": meta["judge_mode"]}
            for tid, meta in selected_tasks.items()
        },
        "contestants": contestants,
        "repetitions": repetitions,
        "budget": {
            "max_steps": max_steps,
            "max_output_tokens": max_output_tokens,
            "timeout_seconds": timeout_seconds,
        },
        "sampling": {
            "temperature": temperature,
            "top_p": top_p,
            "seed": seed,
            "thinking": thinking,
            "context_tokens": context_tokens,
        },
        "environment": {
            "type": "docker",
            "allow_agent_hosts": sorted(hosts) or ["127.0.0.1"],
        },
        "thermal_limit_c": thermal_limit_c,
        "hardware": detect_hardware(),
    }
    target = Path(out_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with open(target, "w", encoding="utf-8") as handle:
        json.dump(doc, handle, indent=2, sort_keys=True)
        handle.write("\n")
    return {
        "initialized": True,
        "study_config": str(target),
        "tasks": len(selected_tasks),
        "contestants": sorted(contestants),
        "binary_sha256": binary_sha,
    }
