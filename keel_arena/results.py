"""Version 1 & 2 normalized result contracts; no model execution or network access."""

import hashlib
import itertools
import json
import math
import re
import statistics
from collections import Counter
from pathlib import Path

SUITES = (
    "coding",
    "tool-use",
    "adversarial",
    "agent-chains",
    "structured",
    "retrieval",
    "instruction",
    "repair",
)
JUDGE_MODES = ("deterministic", "llm_judge", "hybrid")
EDGE_PROFILE_KEYS = {
    "device",
    "weights_vram_gb",
    "kv_per_token_kb",
    "kv_pool_tokens",
    "max_context_tokens",
    "streams_tested",
    "speed_1_stream_tok_s",
    "speed_n_streams_tok_s",
    "ttft_seconds",
    "offload",
    "diagnostic_note",
}


class InvalidResult(ValueError):
    """Input cannot support a trustworthy comparison."""


def require(condition, message):
    if not condition:
        raise InvalidResult(message)


def fields(value, expected, location, optional=""):
    require(isinstance(value, dict), f"{location}: expected object")
    req = set(expected.split())
    opt = set(optional.split())
    keys = set(value)
    require(req.issubset(keys) and keys.issubset(req | opt),
            f"{location}: unexpected or missing fields")


def identifier(value):
    return isinstance(value, str) and bool(re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9._-]{0,95}", value))


def digest(value):
    return isinstance(value, str) and bool(re.fullmatch(r"[0-9a-f]{64}", value))


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


def _validate_edge_profile(profile):
    require(isinstance(profile, dict), "edge_profile must be an object")
    require(set(profile).issubset(EDGE_PROFILE_KEYS), "unexpected field in edge_profile")
    for key in ("device", "offload", "diagnostic_note"):
        if key in profile and profile[key] is not None:
            require(isinstance(profile[key], str) and len(profile[key]) <= 240,
                    f"invalid edge_profile.{key}")
    for key in ("kv_pool_tokens", "max_context_tokens", "streams_tested"):
        if key in profile and profile[key] is not None:
            require(integer(profile[key], 1), f"invalid edge_profile.{key}")
    for key in ("weights_vram_gb", "kv_per_token_kb", "speed_1_stream_tok_s",
                "speed_n_streams_tok_s", "ttft_seconds"):
        if key in profile and profile[key] is not None:
            require(finite(profile[key]), f"invalid edge_profile.{key}")


def _validate_judge_record(judge):
    require(isinstance(judge, dict), "attempt.judge must be an object")
    fields(
        judge,
        "rubric_sha256 judge_model score passed calibrated",
        "attempt.judge",
        optional="deterministic_passed rationale",
    )
    require(digest(judge["rubric_sha256"]), "invalid judge rubric_sha256")
    require(isinstance(judge["judge_model"], str) and 1 <= len(judge["judge_model"]) <= 128,
            "invalid judge_model")
    require(finite(judge["score"]) and judge["score"] <= 1.0, "judge score must be in [0, 1]")
    require(type(judge["passed"]) is bool, "judge passed must be boolean")
    require(type(judge["calibrated"]) is bool, "judge calibrated must be boolean")
    if "deterministic_passed" in judge and judge["deterministic_passed"] is not None:
        require(type(judge["deterministic_passed"]) is bool, "deterministic_passed must be boolean or null")
    if "rationale" in judge and judge["rationale"] is not None:
        require(isinstance(judge["rationale"], str) and len(judge["rationale"]) <= 4096,
                "invalid judge rationale")


def validate_plan(data):
    """Validate the fixed matrix and protocol before any attempts exist."""
    require(isinstance(data, dict) and type(data.get("schema_version")) is int,
            "unsupported schema_version")
    version = data["schema_version"]
    require(version in (1, 2), "unsupported schema_version")
    optional_root = "hardware" if version == 2 else ""
    fields(data, "schema_version purpose protocol tasks contestants repetitions", "plan",
           optional=optional_root)
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
    optional_task = "suite judge_mode" if version == 2 else ""
    for task in data["tasks"].values():
        fields(task, "snapshot_sha256 verifier_sha256 split", "task", optional=optional_task)
        require(digest(task["snapshot_sha256"]) and digest(task["verifier_sha256"]),
                "task requires snapshot and verifier hashes")
        require(task["split"] in ("train", "development", "test"), "invalid task split")
        if "suite" in task and task["suite"] is not None:
            require(task["suite"] in SUITES, "invalid task suite")
        if "judge_mode" in task and task["judge_mode"] is not None:
            require(task["judge_mode"] in JUDGE_MODES, "invalid task judge_mode")
    require(len({task["split"] for task in data["tasks"].values()}) == 1,
            "do not aggregate different task splits")
    optional_contestant = "harness edge_profile" if version == 2 else ""
    for contestant in data["contestants"].values():
        fields(contestant, "model_revision_sha256 quantization", "contestant",
               optional=optional_contestant)
        require(digest(contestant["model_revision_sha256"]), "invalid model revision hash")
        require(identifier(contestant["quantization"]), "invalid quantization")
        if "harness" in contestant and contestant["harness"] is not None:
            require(identifier(contestant["harness"]), "invalid contestant harness")
        if "edge_profile" in contestant and contestant["edge_profile"] is not None:
            _validate_edge_profile(contestant["edge_profile"])
    if version == 2 and "hardware" in data and data["hardware"] is not None:
        require(isinstance(data["hardware"], dict), "hardware must be an object")
    expected_count = len(data["tasks"]) * len(data["contestants"]) * data["repetitions"]
    require(expected_count <= 100_000, "attempt matrix exceeds 100000 cells")
    return data


def validate(data):
    require(isinstance(data, dict) and type(data.get("schema_version")) is int,
            "unsupported schema_version")
    version = data["schema_version"]
    require(version in (1, 2), "unsupported schema_version")
    optional_root = "pairwise calibration hardware" if version == 2 else ""
    fields(data, "schema_version purpose protocol tasks contestants repetitions attempts",
           "result", optional=optional_root)
    plan_keys = {"schema_version", "purpose", "protocol", "tasks", "contestants", "repetitions"}
    if "hardware" in data:
        plan_keys.add("hardware")
    validate_plan({k: v for k, v in data.items() if k in plan_keys})
    require(isinstance(data["attempts"], list), "attempts must be an array")
    expected_count = len(data["tasks"]) * len(data["contestants"]) * data["repetitions"]
    require(len(data["attempts"]) == expected_count, "incomplete or extra attempt matrix")
    optional_attempt = "ttft_seconds decode_tok_s judge" if version == 2 else ""
    seen = set()
    for attempt in data["attempts"]:
        fields(attempt, "task contestant repetition outcome wall_seconds input_tokens output_tokens "
               "trajectory_sha256 verifier_result_sha256", "attempt", optional=optional_attempt)
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
        if version == 2:
            for key in ("ttft_seconds", "decode_tok_s"):
                if key in attempt and attempt[key] is not None:
                    require(finite(attempt[key]), f"invalid {key}")
            if "judge" in attempt and attempt["judge"] is not None:
                _validate_judge_record(attempt["judge"])
    if version == 2 and "pairwise" in data and data["pairwise"] is not None:
        require(isinstance(data["pairwise"], list), "pairwise must be an array")
        for pair in data["pairwise"]:
            fields(pair, "task repetition left right winner position_consistent judge_model rubric_sha256",
                   "pairwise")
            require(pair["task"] in data["tasks"], "pairwise unknown task")
            require(integer(pair["repetition"]) and pair["repetition"] < data["repetitions"],
                    "pairwise invalid repetition")
            require(pair["left"] in data["contestants"] and pair["right"] in data["contestants"]
                    and pair["left"] != pair["right"], "pairwise invalid contestants")
            require(pair["winner"] in ("left", "right", "tie"), "pairwise invalid winner")
            require(type(pair["position_consistent"]) is bool, "position_consistent must be boolean")
            require(isinstance(pair["judge_model"], str) and pair["judge_model"], "invalid judge_model")
            require(digest(pair["rubric_sha256"]), "invalid pairwise rubric_sha256")
    if version == 2 and "calibration" in data and data["calibration"] is not None:
        cal = data["calibration"]
        fields(cal, "judge_human_agreement_rate reviewed_count override_count", "calibration",
               optional="cohens_kappa")
        require(finite(cal["judge_human_agreement_rate"]) and cal["judge_human_agreement_rate"] <= 1.0,
                "invalid judge_human_agreement_rate")
        require(integer(cal["reviewed_count"]) and integer(cal["override_count"]),
                "invalid calibration counts")
        if "cohens_kappa" in cal and cal["cohens_kappa"] is not None:
            require(type(cal["cohens_kappa"]) in (int, float) and math.isfinite(cal["cohens_kappa"])
                    and -1.0 <= cal["cohens_kappa"] <= 1.0, "invalid cohens_kappa")
    return data


def subagent_grade(rate):
    """Assign a clear tier label from a task-mean solve rate."""
    if rate is None:
        return "N/A"
    if rate >= 0.92:
        return "A+"
    if rate >= 0.85:
        return "A"
    if rate >= 0.75:
        return "B"
    if rate >= 0.65:
        return "C"
    if rate >= 0.50:
        return "D"
    return "F"


def compute_elo(contestants, pairwise, k_factor=32.0, initial=1500.0):
    """Deterministic Elo rating update over ordered matched pairwise outcomes."""
    ratings = {name: float(initial) for name in sorted(contestants)}
    stats = {name: {"wins": 0, "losses": 0, "ties": 0, "consistent": 0, "total": 0}
             for name in sorted(contestants)}
    ordered = sorted(
        pairwise,
        key=lambda item: (item["task"], item["repetition"], item["left"], item["right"]),
    )
    for item in ordered:
        left, right, winner = item["left"], item["right"], item["winner"]
        exp_left = 1.0 / (1.0 + 10.0 ** ((ratings[right] - ratings[left]) / 400.0))
        if winner == "left":
            score_left = 1.0
            stats[left]["wins"] += 1
            stats[right]["losses"] += 1
        elif winner == "right":
            score_left = 0.0
            stats[left]["losses"] += 1
            stats[right]["wins"] += 1
        else:
            score_left = 0.5
            stats[left]["ties"] += 1
            stats[right]["ties"] += 1
        for side in (left, right):
            stats[side]["total"] += 1
            if item["position_consistent"]:
                stats[side]["consistent"] += 1
        delta = k_factor * (score_left - exp_left)
        ratings[left] += delta
        ratings[right] -= delta
    return {
        name: {
            "elo": round(ratings[name], 1),
            **stats[name],
            "position_consistency": (
                stats[name]["consistent"] / stats[name]["total"]
                if stats[name]["total"] else None
            ),
        }
        for name in sorted(ratings, key=lambda n: (-ratings[n], n))
    }


def _percentile(values, pct):
    if not values:
        return None
    ordered = sorted(values)
    idx = (len(ordered) - 1) * pct
    lo = math.floor(idx)
    hi = math.ceil(idx)
    if lo == hi:
        return ordered[lo]
    return ordered[lo] + (ordered[hi] - ordered[lo]) * (idx - lo)


def summarize(data, pass_k=(1, 2, 4, 8)):
    validate(data)
    require(isinstance(pass_k, (list, tuple)) and 1 <= len(pass_k) <= 16,
            "request between one and sixteen pass@k values")
    require(all(integer(k, 1) and k <= 100000 for k in pass_k), "invalid pass@k value")
    pass_k = sorted(set(pass_k))
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
        in_tok = _total(eligible, "input_tokens")
        out_tok = _total(eligible, "output_tokens")
        ttft_vals = [r["ttft_seconds"] for r in eligible if r.get("ttft_seconds") is not None]
        decode_vals = [r["decode_tok_s"] for r in eligible if r.get("decode_tok_s") is not None]
        c_meta = data["contestants"][name]
        summaries[name] = {
            "outcomes": dict(sorted(Counter(r["outcome"] for r in own).items())),
            "matched_attempts": len(eligible),
            "matched_solved": len(solved[name]),
            "matched_solve_rate": len(solved[name]) / len(eligible) if eligible else None,
            "matched_wall_seconds": sum(r["wall_seconds"] for r in eligible),
            # Unknown usage remains unknown; never silently treat missing counts as zero.
            "matched_input_tokens": in_tok,
            "matched_output_tokens": out_tok,
            "quantization": c_meta["quantization"],
            "harness": c_meta.get("harness"),
            "edge_profile": c_meta.get("edge_profile"),
            "median_ttft_seconds": statistics.median(ttft_vals) if ttft_vals else None,
            "p95_ttft_seconds": _percentile(ttft_vals, 0.95) if ttft_vals else None,
            "mean_decode_tok_s": statistics.mean(decode_vals) if decode_vals else None,
            "tokens_per_solve": (
                (in_tok + out_tok) / len(solved[name])
                if in_tok is not None and out_tok is not None and len(solved[name]) > 0
                else None
            ),
        }
    per_task = {}
    for task in sorted(data['tasks']):
        eligible_reps = [rep for rep in range(data['repetitions']) if (task, rep) not in excluded]
        models = {}
        for name in sorted(data['contestants']):
            correct = sum((task, rep) in solved[name] for rep in eligible_reps)
            models[name] = {'matched_attempts': len(eligible_reps), 'solved': correct,
                            'solve_rate': correct / len(eligible_reps) if eligible_reps else None}
        task_meta = data['tasks'][task]
        per_task[task] = {
            'matched_repetitions': eligible_reps,
            'excluded_repetitions': [rep for rep in range(data['repetitions'])
                                     if (task, rep) in excluded],
            'suite': task_meta.get('suite'),
            'judge_mode': task_meta.get('judge_mode', 'deterministic'),
            'contestants': models,
        }
    eligible_tasks = [task for task, value in per_task.items() if value['matched_repetitions']]
    for name, summary in summaries.items():
        task_mean = (
            sum(per_task[task]['contestants'][name]['solve_rate'] for task in eligible_tasks) / len(eligible_tasks)
            if eligible_tasks else None)
        summary['matched_task_mean_solve_rate'] = task_mean
        summary['grade'] = subagent_grade(task_mean)
    suites = sorted({t.get('suite') or 'uncategorized' for t in data['tasks'].values()})
    per_suite = {}
    for suite in suites:
        suite_tasks = [task for task in sorted(data['tasks']) if (data['tasks'][task].get('suite') or 'uncategorized') == suite]
        suite_eligible = [task for task in suite_tasks if task in eligible_tasks]
        suite_models = {}
        for name in sorted(data['contestants']):
            solved_count = sum(per_task[task]['contestants'][name]['solved'] for task in suite_eligible)
            attempt_count = sum(per_task[task]['contestants'][name]['matched_attempts'] for task in suite_eligible)
            suite_models[name] = {
                'tasks': len(suite_tasks),
                'eligible_tasks': len(suite_eligible),
                'matched_attempts': attempt_count,
                'solved': solved_count,
                'task_mean_solve_rate': (
                    sum(per_task[task]['contestants'][name]['solve_rate'] for task in suite_eligible) / len(suite_eligible)
                    if suite_eligible else None
                ),
            }
        per_suite[suite] = {'tasks': len(suite_tasks), 'eligible_tasks': len(suite_eligible), 'contestants': suite_models}
    pass_scores = {}
    for k in pass_k:
        cohort = [task for task, value in per_task.items() if len(value['matched_repetitions']) >= k]
        pass_scores[str(k)] = {
            'eligible_task_ids': cohort,
            'contestants': {name: sum(estimate_pass(len(per_task[task]['matched_repetitions']),
                                                   per_task[task]['contestants'][name]['solved'], k)
                                      for task in cohort) / len(cohort) if cohort else None
                            for name in sorted(data['contestants'])}}
    task_differences = []
    for left, right in itertools.combinations(sorted(solved), 2):
        differences = {task: per_task[task]['contestants'][left]['solve_rate'] -
                             per_task[task]['contestants'][right]['solve_rate']
                       for task in eligible_tasks}
        l_tps = summaries[left]["tokens_per_solve"]
        r_tps = summaries[right]["tokens_per_solve"]
        task_differences.append({
            'left': left,
            'right': right,
            'per_task_difference': differences,
            'mean_difference': sum(differences.values()) / len(differences) if differences else None,
            'token_efficiency_ratio': (r_tps / l_tps) if (l_tps and r_tps) else None,
        })
    pairs = []
    for left, right in itertools.combinations(sorted(solved), 2):
        pairs.append({"left": left, "right": right,
                      "left_only_solved": len(solved[left] - solved[right]),
                      "right_only_solved": len(solved[right] - solved[left]),
                      "both_solved": len(solved[left] & solved[right])})
    judge_attempts = [r for r in matched if r.get("judge") is not None]
    calibrated_attempts = [r for r in judge_attempts if r["judge"]["calibrated"]]
    grading_summary = {
        "modes": dict(sorted(Counter(data["tasks"][t].get("judge_mode", "deterministic") for t in data["tasks"]).items())),
        "llm_judged_attempts": len(judge_attempts),
        "human_calibrated_attempts": len(calibrated_attempts),
        "calibration": data.get("calibration"),
    }
    pairwise_data = data.get("pairwise") or []
    elo_ratings = compute_elo(data["contestants"], pairwise_data) if pairwise_data else None
    canonical = json.dumps(data, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    return {
        "schema_version": data["schema_version"],
        "purpose": data["purpose"],
        "result_sha256": hashlib.sha256(canonical).hexdigest(),
        "independent_tasks": len(data["tasks"]),
        "planned_blocks": len(data["tasks"]) * data["repetitions"],
        "excluded_blocks": len(excluded),
        "matched_blocks": len(matched) // len(data["contestants"]),
        "contestants": summaries,
        "per_task": per_task,
        "per_suite": per_suite,
        "tasks_with_matched_attempts": len(eligible_tasks),
        "pass_at_k": pass_scores,
        "paired_task_differences": task_differences,
        "pairwise": pairs,
        "elo_ratings": elo_ratings,
        "grading_summary": grading_summary,
        "hardware": data.get("hardware"),
        "union_solved_blocks": len(set().union(*solved.values())),
    }


def _total(rows, key):
    return sum(r[key] for r in rows) if rows and all(r[key] is not None for r in rows) else None


def estimate_pass(attempts, correct, k):
    """HumanEval's combinatorial estimator, independently implemented with logs."""
    require(integer(attempts, 1) and integer(correct) and correct <= attempts and
            integer(k, 1) and k <= attempts, "pass@k requires 0 <= correct <= attempts and 1 <= k <= attempts")
    if correct == 0:
        return 0.0
    if attempts - correct < k:
        return 1.0
    # C(n-c,k)/C(n,k) == C(n-k,c)/C(n,c). Use the shorter product,
    # log1p/expm1 for numerical stability, and no large combinatorial integers.
    draws, successes = (k, correct) if k <= correct else (correct, k)
    log_failure = sum(math.log1p(-successes / (attempts - index)) for index in range(draws))
    return -math.expm1(log_failure)
