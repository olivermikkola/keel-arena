"""Offline, fail-closed import of explicitly bound Harbor 0.26 single-step trials."""

import hashlib
import json
from datetime import datetime
from pathlib import Path, PurePosixPath

from .results import _object, digest, fields, finite, identifier, integer, require, validate, validate_plan

HARBOR_VERSION = "0.26.0"
# Reviewed against Harbor 0.26.0 error_policy.py. These are model/agent
# outcomes, not grounds for removing a difficult task from a comparison.
GRADED_AGENT_ERRORS = {
    "NonZeroAgentExitCodeError", "ContextWindowExceededError", "OutputTokenExceededError",
    "ContextLengthExceededError", "OutputLengthExceededError", "AgentSafetyRefusalError",
    "ContentPolicyViolationError",
}


def canonical_hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     allow_nan=False).encode()).hexdigest()


def read_bytes(root, relative, optional=False):
    """Read fixed evidence paths only; never follow an artifact symlink."""
    path = PurePosixPath(relative)
    require(not path.is_absolute() and path.parts and
            all(part not in (".", "..") for part in path.parts), "unsafe evidence path")
    target = root
    for part in path.parts:
        target = target / part
        require(not target.is_symlink(), "evidence symlink refused")
    if optional and not target.exists():
        return None
    require(target.is_file(), "missing evidence file")
    with target.open("rb") as source:
        raw = source.read(16 * 1024 * 1024 + 1)
    require(len(raw) <= 16 * 1024 * 1024, "evidence exceeds 16 MiB")
    return raw


def read_json(raw):
    return json.loads(raw, object_pairs_hook=_object)


def validate_manifest(manifest):
    fields(manifest, "schema_version harbor_version reward_metric plan trials", "Harbor manifest")
    require(type(manifest["schema_version"]) is int and manifest["schema_version"] == 1,
            "unsupported import manifest version")
    require(manifest["harbor_version"] == HARBOR_VERSION, "unsupported Harbor version")
    require(identifier(manifest["reward_metric"]), "invalid reward metric")
    plan = validate_plan(manifest["plan"])
    require(isinstance(manifest["trials"], list), "trial bindings must be an array")
    count = len(plan["tasks"]) * len(plan["contestants"]) * plan["repetitions"]
    require(len(manifest["trials"]) == count, "incomplete trial binding matrix")
    seen, directories = set(), set()
    for binding in manifest["trials"]:
        fields(binding, "task contestant repetition directory task_checksum config_sha256", "binding")
        require(isinstance(binding["task"], str) and binding["task"] in plan["tasks"], "unknown task")
        require(isinstance(binding["contestant"], str) and
                binding["contestant"] in plan["contestants"], "unknown contestant")
        require(integer(binding["repetition"]) and binding["repetition"] < plan["repetitions"],
                "invalid repetition")
        cell = (binding["task"], binding["contestant"], binding["repetition"])
        require(cell not in seen, "duplicate trial cell")
        seen.add(cell)
        require(isinstance(binding["directory"], str) and binding["directory"], "invalid trial directory")
        path = PurePosixPath(binding["directory"])
        require(not path.is_absolute() and all(p not in (".", "..") for p in path.parts),
                "unsafe trial directory")
        require(path.as_posix() not in directories, "trial directory reused")
        directories.add(path.as_posix())
        require(digest(binding["config_sha256"]), "invalid config digest")
        # Harbor's dirhash checksum is not Arena's snapshot SHA-256. Preserve
        # the expected native value independently; do not pretend they match.
        require(isinstance(binding["task_checksum"], str) and
                1 <= len(binding["task_checksum"]) <= 128, "invalid native task checksum")
    return manifest


def _wall_seconds(trial):
    phase = trial
    times = []
    for key in ("started_at", "finished_at"):
        require(isinstance(phase.get(key), str), "unfinished execution timing")
        value = datetime.fromisoformat(phase[key].replace("Z", "+00:00"))
        require(value.tzinfo is not None and value.utcoffset() is not None,
                "execution timestamps require timezone")
        times.append(value)
    seconds = (times[1] - times[0]).total_seconds()
    require(finite(seconds), "invalid execution duration")
    return seconds


def _outcome(trial, root, directory, metric):
    exception = trial.get("exception_info")
    if exception is not None:
        require(isinstance(exception, dict) and isinstance(exception.get("exception_type"), str),
                "invalid exception record")
        # Fail closed on unknown failures. Do not interpret backend-specific
        # serialized policy overrides as permission to count a reward.
        kind = exception["exception_type"]
        if kind == "AgentTimeoutError":
            return "timeout", None
        if kind not in GRADED_AGENT_ERRORS:
            return "infrastructure_error", None
    require(trial.get("reward_valid") is True, "trial has no valid verifier reward")
    verifier = trial.get("verifier_result")
    require(isinstance(verifier, dict) and isinstance(verifier.get("rewards"), dict),
            "missing verifier rewards")
    rewards = verifier["rewards"]
    require(set(rewards) == {metric}, "ambiguous verifier reward metrics")
    reward = rewards[metric]
    require(type(reward) in (int, float) and reward in (0, 1), "reward must be binary")
    text = read_bytes(root, f"{directory}/verifier/reward.txt", optional=True)
    structured = read_bytes(root, f"{directory}/verifier/reward.json", optional=True)
    require((text is None) != (structured is None), "require exactly one verifier reward artifact")
    raw = text if text is not None else structured
    actual = float(text.decode().strip()) if text is not None else read_json(structured)
    if structured is not None:
        require(isinstance(actual, dict) and set(actual) == {metric}, "ambiguous reward artifact")
        actual = actual[metric]
    require(type(actual) in (int, float) and actual in (0, 1) and actual == reward,
            "verifier reward artifact disagrees with trial")
    return ("solved" if reward == 1 else "unsolved"), hashlib.sha256(raw).hexdigest()


def import_trials(manifest, jobs_root):
    validate_manifest(manifest)
    root = Path(jobs_root)
    require(root.is_dir() and not root.is_symlink(), "invalid jobs root")
    output = dict(manifest["plan"], attempts=[])
    for binding in manifest["trials"]:
        directory = binding["directory"]
        trial_bytes = read_bytes(root, f"{directory}/result.json")
        trial = read_json(trial_bytes)
        require(isinstance(trial, dict) and type(trial.get("schema_version", 1)) is int
                and trial.get("schema_version", 1) == 1,
                "unsupported trial schema")
        require(trial.get("finished_at") is not None, "unfinished trial")
        require(trial.get("task_name") == binding["task"], "trial task identity mismatch")
        require(trial.get("task_checksum") == binding["task_checksum"], "task checksum mismatch")
        require(not trial.get("step_results"), "multi-step trials not supported")
        config = trial.get("config")
        require(isinstance(config, dict) and canonical_hash(config) == binding["config_sha256"],
                "trial config differs from frozen binding")
        require(not config.get("install_only") and not config.get("source_trial"),
                "setup-only and regraded trials not supported")
        require(isinstance(config.get("verifier"), dict) and
                config["verifier"].get("disable") is False, "verifier must be enabled")
        wall = _wall_seconds(trial)
        outcome, verifier_hash = _outcome(trial, root, directory, manifest["reward_metric"])
        if verifier_hash is not None:
            verifier_hash = hashlib.sha256(trial_bytes).hexdigest()
        trajectory = read_bytes(root, f"{directory}/agent/trajectory.json", optional=True)
        usage = trial.get("agent_result") or {}
        require(isinstance(usage, dict), "invalid usage object")
        output["attempts"].append({
            "task": binding["task"], "contestant": binding["contestant"],
            "repetition": binding["repetition"], "outcome": outcome, "wall_seconds": wall,
            "input_tokens": usage.get("n_input_tokens"), "output_tokens": usage.get("n_output_tokens"),
            "trajectory_sha256": hashlib.sha256(trajectory).hexdigest() if trajectory is not None else None,
            "verifier_result_sha256": verifier_hash,
        })
    return validate(output)
