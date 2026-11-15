"""Version 1 normalized result contract; no model execution or network access."""

import hashlib
import itertools
import json
import math
import re
from collections import Counter
from pathlib import Path


class InvalidResult(ValueError):
    """Input cannot support a trustworthy comparison."""


def require(condition, message):
    if not condition:
        raise InvalidResult(message)


def fields(value, expected, location):
    require(isinstance(value, dict), f"{location}: expected object")
    require(set(value) == set(expected.split()), f"{location}: unexpected or missing fields")


def identifier(value):
    return isinstance(value, str) and re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9._-]{0,95}", value)


def digest(value):
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value)


def integer(value, minimum=0):
    return type(value) is int and value >= minimum


def finite(value, minimum=0):
    return type(value) in (int, float) and minimum <= value <= 1e15 and math.isfinite(value)


def _object(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, "duplicate JSON object key")
        result[key] = value
    return result


def load(path):
    """Reject ambiguous JSON, then validate the entire planned attempt matrix."""
    with Path(path).open("rb") as source:
        raw = source.read(16 * 1024 * 1024 + 1)
    require(len(raw) <= 16 * 1024 * 1024, "input exceeds 16 MiB")
    data = json.loads(raw, object_pairs_hook=_object)
    validate(data)
    return data


def validate(data):
    fields(data, "schema_version purpose protocol tasks contestants repetitions attempts", "result")
    require(type(data["schema_version"]) is int and data["schema_version"] == 1,
            "unsupported schema_version")
    require(data["purpose"] in ("demonstration", "benchmark"), "invalid purpose")
    protocol = data["protocol"]
    fields(protocol, "harness_revision environment_sha256 sampling_sha256 budget", "protocol")
    require(digest(protocol["harness_revision"]), "harness_revision must be executable SHA-256")
    for key in ("environment_sha256", "sampling_sha256"):
        require(digest(protocol[key]), f"invalid {key}")
    budget = protocol["budget"]
    fields(budget, "max_steps max_output_tokens timeout_seconds", "budget")
    require(all(integer(v, 1) for v in budget.values()), "budgets must be positive integers")
    require(integer(data["repetitions"], 1), "repetitions must be positive")
    for name in ("tasks", "contestants"):
        require(isinstance(data[name], dict) and data[name], f"{name} must be a nonempty object")
        require(all(identifier(k) for k in data[name]), f"invalid {name} identifier")
    require(len(data["contestants"]) <= 64, "at most 64 contestants per comparison")
    for task in data["tasks"].values():
        fields(task, "snapshot_sha256 verifier_sha256 split", "task")
        require(digest(task["snapshot_sha256"]) and digest(task["verifier_sha256"]),
                "task requires snapshot and verifier hashes")
        require(task["split"] in ("train", "development", "test"), "invalid task split")
    require(len({task["split"] for task in data["tasks"].values()}) == 1,
            "do not aggregate different task splits")
    for contestant in data["contestants"].values():
        fields(contestant, "model_revision_sha256 quantization", "contestant")
        require(digest(contestant["model_revision_sha256"]), "invalid model revision hash")
        require(identifier(contestant["quantization"]), "invalid quantization")
    require(isinstance(data["attempts"], list), "attempts must be an array")
    expected_count = len(data["tasks"]) * len(data["contestants"]) * data["repetitions"]
    require(expected_count <= 100_000, "attempt matrix exceeds 100000 cells")
    require(len(data["attempts"]) == expected_count, "incomplete or extra attempt matrix")
    seen = set()
    for attempt in data["attempts"]:
        fields(attempt, "task contestant repetition outcome wall_seconds input_tokens output_tokens "
               "trajectory_sha256 verifier_result_sha256", "attempt")
        require(isinstance(attempt["task"], str) and attempt["task"] in data["tasks"],
                "unknown task")
        require(isinstance(attempt["contestant"], str) and
                attempt["contestant"] in data["contestants"], "unknown contestant")
        rep = attempt["repetition"]
        require(integer(rep) and rep < data["repetitions"], "invalid repetition")
        cell = (attempt["task"], attempt["contestant"], rep)
        require(cell not in seen, "duplicate attempt cell")
        seen.add(cell)
        require(attempt["outcome"] in ("solved", "unsolved", "timeout", "infrastructure_error"),
                "invalid outcome")
        require(finite(attempt["wall_seconds"]), "invalid wall_seconds")
        for key in ("input_tokens", "output_tokens"):
            require(attempt[key] is None or integer(attempt[key]), f"invalid {key}")
        for key in ("trajectory_sha256", "verifier_result_sha256"):
            require(attempt[key] is None or digest(attempt[key]), f"invalid {key}")
        if attempt["outcome"] in ("solved", "unsolved"):
            require(digest(attempt["verifier_result_sha256"]),
                    "graded outcomes require verifier result hash")
    return data


def summarize(data):
    validate(data)
    rows = data["attempts"]
    # One infrastructure failure excludes that block for every contestant.
    excluded = {(r["task"], r["repetition"]) for r in rows
                if r["outcome"] == "infrastructure_error"}
    matched = [r for r in rows if (r["task"], r["repetition"]) not in excluded]
    solved = {name: {(r["task"], r["repetition"]) for r in matched
                     if r["contestant"] == name and r["outcome"] == "solved"}
              for name in data["contestants"]}
    summaries = {}
    for name in sorted(data["contestants"]):
        own = [r for r in rows if r["contestant"] == name]
        eligible = [r for r in matched if r["contestant"] == name]
        summaries[name] = {
            "outcomes": dict(sorted(Counter(r["outcome"] for r in own).items())),
            "matched_attempts": len(eligible),
            "matched_solved": len(solved[name]),
            "matched_solve_rate": len(solved[name]) / len(eligible) if eligible else None,
            "matched_wall_seconds": sum(r["wall_seconds"] for r in eligible),
            # Unknown usage remains unknown; never silently treat missing counts as zero.
            "matched_input_tokens": _total(eligible, "input_tokens"),
            "matched_output_tokens": _total(eligible, "output_tokens"),
        }
    pairs = []
    for left, right in itertools.combinations(sorted(solved), 2):
        pairs.append({"left": left, "right": right,
                      "left_only_solved": len(solved[left] - solved[right]),
                      "right_only_solved": len(solved[right] - solved[left]),
                      "both_solved": len(solved[left] & solved[right])})
    canonical = json.dumps(data, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    return {
        "schema_version": 1,
        "purpose": data["purpose"],
        "result_sha256": hashlib.sha256(canonical).hexdigest(),
        "independent_tasks": len(data["tasks"]),
        "planned_blocks": len(data["tasks"]) * data["repetitions"],
        "excluded_blocks": len(excluded),
        "matched_blocks": len(matched) // len(data["contestants"]),
        "contestants": summaries,
        "pairwise": pairs,
        "union_solved_blocks": len(set().union(*solved.values())),
    }


def _total(rows, key):
    return sum(r[key] for r in rows) if rows and all(r[key] is not None for r in rows) else None
