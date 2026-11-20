"""Offline paired comparison of saved Keel Mobile harness-eval runs.

Reads the per-attempt JSONL that Keel Mobile's ``tools/harness-eval`` agent eval
writes with ``--out``, plus the provenance files saved beside it. It never runs
inference, contacts a server or executes task content.
"""

import hashlib
import json
import math
import re
from collections import Counter
from pathlib import Path

from .results import InvalidResult, _object, require

MAX_FILE_BYTES = 64 * 1024 * 1024
MAX_SIDE_FILES = 64
TASK_ID = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9._-]{0,95}")
SUITE_ID = TASK_ID
SETUP_KEY = re.compile(r"[a-z][a-z0-9_.-]{0,47}")
OUTCOMES = ("solved", "unsolved", "timeout", "infrastructure_error")
COUNTERS = {
    "steps": "steps",
    "rejected": "rejected_calls",
    "toolErrors": "tool_errors",
    "wrappedCalls": "json_wrapped_calls",
    "prefillTokens": "prefill_tokens",
    "generatedTokens": "generated_tokens",
    "proposals": "proposals",
    "staleProposals": "stale_proposals",
    "scriptCalls": "script_calls",
    "userTurns": "user_turns",
    "callSteps": "call_steps",
    "narrationCharacters": "narration_characters",
    "cacheMisses": "cache_misses",
}
# Reviewed against keel-mobile tools/harness-eval/agent/main.swift (Fatal.stop and
# the generic error catch). Budget exhaustion is a timeout in Arena's contract;
# a malformed model call is an ordinary failure; anything else is treated as
# infrastructure, conservatively, until it is reviewed and added here.
BUDGET_STOPS = {
    "tool limit": "step_limit",
    "invalid call at limit": "step_limit",
    "call cut off by the reply limit": "reply_limit",
    "context overflow": "context_limit",
}
REQUEST_TIMEOUT = re.compile(r"Code=-1001\b|timed ?out", re.IGNORECASE)


def classify_stop(fatal):
    """Map a harness ``fatal`` string to (outcome class, stop label); never echo it."""
    if fatal is None:
        return None, None
    if fatal in BUDGET_STOPS:
        return "timeout", BUDGET_STOPS[fatal]
    if fatal.startswith("invalid call:") or fatal == "tool failure: call":
        return "unsolved", "invalid_call"
    if fatal.startswith("error:") and REQUEST_TIMEOUT.search(fatal):
        return "timeout", "request_timeout"
    if fatal.startswith("tool failure:"):
        return "infrastructure_error", "tool_failure"
    if fatal.startswith("error:"):
        return "infrastructure_error", "harness_error"
    return "infrastructure_error", "unreviewed_stop"


def classify(row):
    """Arena outcome for one harness attempt."""
    kind, stop = classify_stop(row.get("fatal"))
    if kind == "infrastructure_error":
        return kind, stop
    if not row["success"] and str(row.get("checkOutput", "")).startswith("check could not run"):
        return "infrastructure_error", "check_error"
    if row["success"]:
        return "solved", stop
    return kind or "unsolved", stop


def _bounded(path):
    require(not path.is_symlink(), "symlinked run file refused")
    require(path.is_file(), "missing run file")
    with path.open("rb") as source:
        raw = source.read(MAX_FILE_BYTES + 1)
    require(len(raw) <= MAX_FILE_BYTES, "run file exceeds 64 MiB")
    return raw


def _int(row, key):
    value = row.get(key, 0)
    require(type(value) is int and value >= 0, "attempt counter must be a nonnegative integer")
    return value


def parse_attempts(raw):
    """Validate harness-eval JSONL rows; returns one record per (task, sample)."""
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        raise InvalidResult("attempt file is not UTF-8") from None
    attempts = {}
    for line in text.splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line, object_pairs_hook=_object)
        except ValueError:
            raise InvalidResult("attempt line is not one JSON object") from None
        require(isinstance(row, dict), "attempt line is not one JSON object")
        require(isinstance(row.get("task"), str) and TASK_ID.fullmatch(row["task"]), "invalid attempt task id")
        require(type(row.get("sample")) is int and 0 <= row["sample"] < 100_000, "invalid attempt sample")
        require(type(row.get("success")) is bool, "attempt success must be boolean")
        seconds = row.get("seconds")
        require(type(seconds) in (int, float) and math.isfinite(seconds) and 0 <= seconds <= 1e9,
                "invalid attempt seconds")
        require(row.get("fatal") is None or isinstance(row["fatal"], str), "invalid attempt stop")
        require(isinstance(row.get("checkOutput", ""), str), "invalid attempt check output")
        key = (row["task"], row["sample"])
        require(key not in attempts, "duplicate attempt in one suite")
        outcome, stop = classify(row)
        record = {"outcome": outcome, "stop": stop, "seconds": float(seconds)}
        for source, name in COUNTERS.items():
            record[name] = _int(row, source)
        attempts[key] = record
    require(attempts, "attempt file has no attempts")
    return attempts


def parse_header(text):
    """Read the setup lines and completion summary that harness-eval prints."""
    header, sampler, finished = {}, {}, False
    for line in text.splitlines()[:4000]:
        if line.startswith("model: ") and not header:
            for part in re.split(r"\s{2,}", line.strip()):
                key, _, value = part.partition(": ")
                if key in ("model", "family", "grammar", "tools", "context", "samples", "tasks"):
                    header[key] = value.strip()[:120]
        elif line.startswith("sampler: ") and not sampler:
            for part in line[len("sampler: "):].split(", "):
                key, _, value = part.strip().partition(" ")
                if re.fullmatch(r"[a-z_]{1,32}", key):
                    sampler[key] = value.strip()[:40] or "on"
        elif re.match(r"all\s+\d+/\d+ passed", line):
            finished = True
    for key in ("context", "samples", "tasks"):
        if key in header:
            header[key] = int(header[key]) if header[key].isdigit() else None
    return header, sampler, finished


def parse_server_log(raw):
    """Numeric llama-server settings and observed speed; no paths or prompts."""
    text = raw.decode("utf-8", errors="replace")
    threads = sorted({int(v) for v in re.findall(r"llama threadpool init, n_threads = (\d+)", text)})
    slots = sorted({int(v) for v in re.findall(r"n_slots = (\d+)", text)})
    contexts = sorted({int(v) for v in re.findall(r"n_ctx_slot = (\d+)", text)})
    builds = sorted(set(re.findall(r"\bbuild[:=]\s*(b?\d{3,6})\b", text)))
    devices = sorted(set(re.findall(r"\b(Vulkan|CUDA|Metal|ROCm|SYCL)\d*\b", text)))
    starts = len(re.findall(r"llama_server: initializing", text)) or None

    def speed(pattern):
        pairs = [(float(ms), int(n)) for ms, n in re.findall(pattern, text)]
        ms = sum(p[0] for p in pairs)
        return round(sum(p[1] for p in pairs) / ms * 1000, 1) if ms > 0 else None

    return {
        "starts": starts,
        "threads": threads,
        "slots": slots,
        "context_per_slot": contexts,
        "build": builds,
        "backend_hint": devices,
        "observed_prompt_tok_s": speed(r"prompt eval time =\s*([\d.]+) ms /\s*(\d+) tokens"),
        "observed_generation_tok_s": speed(r"\|\s+eval time =\s*([\d.]+) ms /\s*(\d+) tokens"),
    }


def _first_hex(raw, length):
    match = re.match(rb"\s*([0-9a-f]{%d})\b" % length, raw)
    return match.group(1).decode() if match else None


def parse_setup_pairs(pairs):
    declared = {}
    for pair in pairs or []:
        key, sep, value = pair.partition("=")
        require(sep and SETUP_KEY.fullmatch(key) and 0 < len(value) <= 120 and value.isprintable(),
                "declared setup must be key=value with a short lowercase key")
        require(key not in declared, "duplicate declared setup key")
        declared[key] = value
    return declared


def load_run(path, declared=None, label=None):
    """Load one saved setup: a directory of SUITE.jsonl (+ SUITE.txt), or one JSONL file."""
    path = Path(path)
    require(not path.is_symlink(), "symlinked run path refused")
    if path.is_dir():
        files = sorted(p for p in path.iterdir() if p.suffix == ".jsonl" and not p.is_symlink() and p.is_file())
        directory = path
    else:
        require(path.suffix == ".jsonl", "run path must be a directory or a .jsonl file")
        files, directory = [path], path.parent
    require(files, "run has no .jsonl attempt files")
    require(len(files) <= MAX_SIDE_FILES, "too many attempt files in one run")
    suites = {}
    for file in files:
        name = file.stem
        require(SUITE_ID.fullmatch(name), "attempt file name is not a simple suite id")
        attempts = parse_attempts(_bounded(file))
        log = file.with_suffix(".txt")
        header, sampler, finished = ({}, {}, None)
        if log.exists():
            header, sampler, finished = parse_header(_bounded(log).decode("utf-8", errors="replace"))
        expected = (header["tasks"] * header["samples"]
                    if isinstance(header.get("tasks"), int) and isinstance(header.get("samples"), int) else None)
        samples_by_task = Counter(task for task, _ in attempts)
        uniform = len(set(samples_by_task.values())) == 1 and all(
            (task, s) in attempts for task in samples_by_task for s in range(samples_by_task[task]))
        suites[name] = {
            "attempts": attempts,
            "header": header,
            "sampler": sampler,
            "attempt_file_sha256": hashlib.sha256(_bounded(file)).hexdigest(),
            "recorded_attempts": len(attempts),
            "expected_attempts": expected,
            "finished": finished,
            "complete": bool(finished) and expected == len(attempts) and uniform,
        }
    provenance = {"model_file": None, "model_sha256": None, "harness_commit": None, "server": None}
    sha_file = directory / "model.sha256"
    if sha_file.is_file() and not sha_file.is_symlink():
        raw = _bounded(sha_file)
        provenance["model_sha256"] = _first_hex(raw, 64)
        parts = raw.decode("utf-8", errors="replace").split()
        if len(parts) >= 2:
            provenance["model_file"] = parts[1].replace("\\", "/").rsplit("/", 1)[-1][:120]
    for candidate in (directory / "keel-mobile-commit.txt", directory.parent / "keel-mobile-commit.txt"):
        if candidate.is_file() and not candidate.is_symlink():
            provenance["harness_commit"] = _first_hex(_bounded(candidate), 40)
            break
    for candidate in (directory / "server.log", directory / "server.txt"):
        if candidate.is_file() and not candidate.is_symlink():
            provenance["server"] = parse_server_log(_bounded(candidate))
            break
    if label is None:
        label = path.stem if path.is_file() else path.name
    return {"label": label, "suites": suites, "provenance": provenance,
            "declared": dict(declared or {})}


def _setup_view(run, suite):
    data = run["suites"][suite]
    server = run["provenance"]["server"] or {}
    view = {"harness_commit": run["provenance"]["harness_commit"],
            "model_file": run["provenance"]["model_file"],
            "model_sha256": run["provenance"]["model_sha256"]}
    for key, value in data["header"].items():
        if key == "model" and value == view["model_file"]:
            continue  # the same file name, already shown as model_file
        view["eval." + key] = value
    for key, value in data["sampler"].items():
        view["sampler." + key] = value
    for key in ("threads", "slots", "context_per_slot", "build", "backend_hint"):
        if server.get(key):
            view["server." + key] = ",".join(str(v) for v in server[key])
    for key, value in run["declared"].items():
        view["declared." + key] = value
    return view


def _diff(left, right, scope):
    out = []
    for key in sorted(set(left) | set(right)):
        a, b = left.get(key), right.get(key)
        if a is None or b is None:
            if a != b and key.startswith("declared."):
                out.append({"scope": scope, "field": key, "left": a, "right": b})
            continue
        if a != b:
            out.append({"scope": scope, "field": key, "left": a, "right": b})
    return out


def _label(record):
    if record["outcome"] in ("timeout", "infrastructure_error") or record["stop"]:
        return f"{record['outcome']}:{record['stop']}" if record["stop"] else record["outcome"]
    return record["outcome"]


def compare_runs(left, right, suites=None):
    """Paired report over (suite, task, sample) cells recorded in both runs."""
    common = sorted(set(left["suites"]) & set(right["suites"]))
    if suites:
        require(all(s in common for s in suites), "requested suite is not in both runs")
        common = sorted(set(suites))
    require(common, "the runs share no suite")
    warnings = []
    differences = []
    for suite in common:
        differences += _diff(_setup_view(left, suite), _setup_view(right, suite), suite)
    # Collapse fields that differ identically in every suite into one run-level row.
    collapsed, seen = [], {}
    for item in differences:
        seen.setdefault((item["field"], json.dumps(item["left"]), json.dumps(item["right"])), []).append(item["scope"])
    for (field, a, b), scopes in seen.items():
        collapsed.append({"field": field, "suites": "all" if len(scopes) == len(common) else ",".join(scopes),
                          "left": json.loads(a), "right": json.loads(b)})
    observed = {}
    ls, rs = left["provenance"]["server"] or {}, right["provenance"]["server"] or {}
    for key in ("observed_prompt_tok_s", "observed_generation_tok_s"):
        a, b = ls.get(key), rs.get(key)
        observed[key] = {"left": a, "right": b,
                         "ratio": round(b / a, 2) if a and b else None}
    speed_shift = any(v["ratio"] and (v["ratio"] >= 1.5 or v["ratio"] <= 1 / 1.5) for v in observed.values())
    recorded = [d for d in collapsed if not d["field"].startswith("declared.")]
    declared = [d for d in collapsed if d["field"].startswith("declared.")]
    if speed_shift and not declared:
        warnings.append("observed server speed differs by 1.5x or more but no setup difference is declared; "
                        "backend or hardware may have changed (declare it with --left-setup/--right-setup)")
    if not recorded and not declared:
        warnings.append("no recorded or declared setup difference: score changes cannot be attributed to a setup")
    for side, run in (("left", left), ("right", right)):
        if run["provenance"]["harness_commit"] is None:
            warnings.append(f"{side}: harness commit not recorded; seeds and tasks may not match")
        if run["provenance"]["model_sha256"] is None:
            warnings.append(f"{side}: model digest not recorded")
        for suite in common:
            data = run["suites"][suite]
            if not data["complete"]:
                warnings.append(f"{side}: suite {suite} is incomplete or unfinished "
                                f"({data['recorded_attempts']} of {data['expected_attempts'] or 'unknown'} attempts)")
    if any(d["field"] == "harness_commit" for d in collapsed):
        warnings.append("harness commits differ: task order, seeds, prompts or checks may differ")

    cells, left_only, right_only = [], [], []
    for suite in common:
        la, ra = left["suites"][suite]["attempts"], right["suites"][suite]["attempts"]
        for key in sorted(set(la) | set(ra)):
            if key in la and key in ra:
                cells.append((suite, key[0], key[1], la[key], ra[key]))
            elif key in la:
                left_only.append(f"{suite}/{key[0]}#{key[1]}")
            else:
                right_only.append(f"{suite}/{key[0]}#{key[1]}")
    if left_only or right_only:
        warnings.append(f"{len(left_only) + len(right_only)} attempt cells are recorded on one side only and are "
                        "not compared")
    excluded = [c for c in cells if "infrastructure_error" in (c[3]["outcome"], c[4]["outcome"])]
    matched = [c for c in cells if c not in excluded]

    def totals(index):
        rows = [c[index] for c in matched]
        out = {"attempts": len(rows),
               "solved": sum(r["outcome"] == "solved" for r in rows),
               "outcomes": {k: sum(r["outcome"] == k for r in rows) for k in OUTCOMES[:3]},
               "seconds": round(sum(r["seconds"] for r in rows), 1)}
        out["solve_rate"] = out["solved"] / len(rows) if rows else None
        for name in COUNTERS.values():
            out[name] = sum(r[name] for r in rows)
        out["stops"] = dict(sorted(Counter(r["stop"] for r in rows if r["stop"]).items()))
        out["mean_narration_chars_per_call"] = (
            round(out["narration_characters"] / out["call_steps"], 1) if out["call_steps"] else None
        )
        return out

    per_suite = {}
    for suite in common:
        rows = [c for c in matched if c[0] == suite]
        per_suite[suite] = {"attempts": len(rows),
                            "left_solved": sum(c[3]["outcome"] == "solved" for c in rows),
                            "right_solved": sum(c[4]["outcome"] == "solved" for c in rows)}
    paired = Counter()
    for c in matched:
        a, b = c[3]["outcome"] == "solved", c[4]["outcome"] == "solved"
        paired["both_solved" if a and b else "left_only_solved" if a else "right_only_solved" if b
               else "neither_solved"] += 1
    tasks = {}
    for suite, task, sample, a, b in matched:
        entry = tasks.setdefault((suite, task), {"suite": suite, "task": task, "attempts": 0, "left_solved": 0,
                                                 "right_solved": 0, "samples": []})
        entry["attempts"] += 1
        entry["left_solved"] += a["outcome"] == "solved"
        entry["right_solved"] += b["outcome"] == "solved"
        if _label(a) != _label(b):
            entry["samples"].append({"sample": sample, "left": _label(a), "right": _label(b)})
    changed = []
    for entry in tasks.values():
        entry["difference"] = entry["right_solved"] - entry["left_solved"]
        if entry["samples"]:
            changed.append(entry)
    changed.sort(key=lambda e: (-abs(e["difference"]), e["difference"], e["suite"], e["task"]))
    timeouts = [{"suite": s, "task": t, "sample": n, "left": _label(a), "right": _label(b)}
                for s, t, n, a, b in matched if "timeout" in (a["outcome"], b["outcome"])]
    infra = [{"suite": s, "task": t, "sample": n, "left": _label(a), "right": _label(b)}
             for s, t, n, a, b in excluded]
    left_totals, right_totals = totals(3), totals(4)
    return {
        "schema_version": 1,
        "kind": "keel_mobile_paired_comparison",
        "purpose": "local comparison of saved runs; not a significance test or promotion decision",
        "left": _side(left, common),
        "right": _side(right, common),
        "suites": common,
        "not_compared_suites": {"left": sorted(set(left["suites"]) - set(common)),
                             "right": sorted(set(right["suites"]) - set(common))},
        "setup_differences": collapsed,
        "observed_speed": observed,
        "warnings": warnings,
        "matched_attempts": len(matched),
        "excluded_infrastructure_attempts": infra,
        "one_side_only": {"left": left_only, "right": right_only},
        "totals": {"left": left_totals, "right": right_totals,
                   "solved_difference": right_totals["solved"] - left_totals["solved"]},
        "per_suite": per_suite,
        "paired": {k: paired.get(k, 0) for k in ("both_solved", "left_only_solved", "right_only_solved",
                                                 "neither_solved")},
        "changed_tasks": changed,
        "unchanged_tasks": len(tasks) - len(changed),
        "timeouts": timeouts,
    }


def _side(run, suites):
    return {
        "label": run["label"],
        "provenance": run["provenance"],
        "declared": run["declared"],
        "suites": {name: {k: data[k] for k in ("recorded_attempts", "expected_attempts", "finished", "complete",
                                               "attempt_file_sha256")}
                   for name, data in sorted(run["suites"].items())},
        "compared_suites": suites,
    }


def _cell(value):
    return "not recorded" if value is None else str(value).replace("|", "\\|")


def markdown(report):
    left, right = report["left"]["label"], report["right"]["label"]
    t = report["totals"]
    diff = t["solved_difference"]

    def rate(row):
        return f"{row['solved']}/{row['attempts']}" + (f" ({row['solve_rate']:.1%})" if row["attempts"] else "")

    lines = ["# Keel Mobile paired comparison", "",
             f"**{left}** {rate(t['left'])} → **{right}** {rate(t['right'])}: **{diff:+d}** solved "
             f"over {report['matched_attempts']} matched attempts in suites {', '.join(report['suites'])}.", ""]
    if report["warnings"]:
        lines += ["## Warnings", ""] + [f"- {w}" for w in report["warnings"]] + [""]
    lines += ["## Where the setups differ", ""]
    if report["setup_differences"]:
        lines += ["| Field | Suites | " + left + " | " + right + " |", "| --- | --- | --- | --- |"]
        for d in report["setup_differences"]:
            lines.append(f"| {d['field']} | {d['suites']} | {_cell(d['left'])} | {_cell(d['right'])} |")
    else:
        lines.append("No recorded or declared difference in model digest, harness commit, eval flags, sampler "
                     "or server settings.")
    obs = report["observed_speed"]
    lines += ["", "Observed server speed (from server.log; a symptom, not a setting):", "",
              f"| Metric | {left} | {right} | Ratio |", "| --- | ---: | ---: | ---: |"]
    for key, name in (("observed_prompt_tok_s", "Prompt tok/s"), ("observed_generation_tok_s", "Generation tok/s")):
        lines.append(f"| {name} | {_cell(obs[key]['left'])} | {_cell(obs[key]['right'])} | "
                     f"{_cell(obs[key]['ratio'])} |")
    lines += ["", "## Outcomes", "",
              f"| Suite | Matched attempts | {left} solved | {right} solved | Difference |",
              "| --- | ---: | ---: | ---: | ---: |"]
    for suite, row in report["per_suite"].items():
        lines.append(f"| {suite} | {row['attempts']} | {row['left_solved']} | {row['right_solved']} | "
                     f"{row['right_solved'] - row['left_solved']:+d} |")
    p = report["paired"]
    lines += ["", f"Paired attempts: both solved {p['both_solved']}, only {left} {p['left_only_solved']}, "
              f"only {right} {p['right_only_solved']}, neither {p['neither_solved']}.", "",
              f"| Measure (matched attempts) | {left} | {right} |", "| --- | ---: | ---: |"]
    for key, name in (("timeout", "Timed out"), ("unsolved", "Unsolved")):
        lines.append(f"| {name} | {t['left']['outcomes'][key]} | {t['right']['outcomes'][key]} |")
    for key, name in (("steps", "Tool steps"), ("generated_tokens", "Generated tokens"),
                      ("prefill_tokens", "Prefill tokens"), ("rejected_calls", "Rejected calls"),
                      ("json_wrapped_calls", "JSON-wrapped calls"), ("tool_errors", "Tool errors"),
                      ("script_calls", "Script calls (run_js)"), ("narration_characters", "Narration characters"),
                      ("cache_misses", "Cache misses"), ("seconds", "Seconds")):
        lines.append(f"| {name} | {t['left'][key]} | {t['right'][key]} |")
    lines.append(f"| Narration chars / tool call | {_cell(t['left']['mean_narration_chars_per_call'])} | "
                 f"{_cell(t['right']['mean_narration_chars_per_call'])} |")
    for key, name in (("generated_tokens", "Generated tokens per attempt"), ("seconds", "Seconds per attempt")):
        lines.append(f"| {name} | " + " | ".join(
            f"{t[side][key] / t[side]['attempts']:.1f}" if t[side]["attempts"] else "not recorded"
            for side in ("left", "right")) + " |")
    lines += ["", "## Tasks that changed", ""]
    if report["changed_tasks"]:
        lines += [f"| Suite | Task | {left} | {right} | Difference | Samples that changed ({left} → {right}) |",
                  "| --- | --- | ---: | ---: | ---: | --- |"]
        for e in report["changed_tasks"]:
            samples = "; ".join(f"#{s['sample']} {s['left']} → {s['right']}" for s in e["samples"])
            lines.append(f"| {e['suite']} | {e['task']} | {e['left_solved']}/{e['attempts']} | "
                         f"{e['right_solved']}/{e['attempts']} | {e['difference']:+d} | {samples} |")
    else:
        lines.append("No matched attempt changed outcome.")
    lines += ["", f"{report['unchanged_tasks']} tasks had identical outcomes on every matched sample.", "",
              "## Timeouts", ""]
    if report["timeouts"]:
        lines += [f"| Suite | Task | Sample | {left} | {right} |", "| --- | --- | ---: | --- | --- |"]
        for e in report["timeouts"]:
            lines.append(f"| {e['suite']} | {e['task']} | {e['sample']} | {e['left']} | {e['right']} |")
    else:
        lines.append("No matched attempt timed out.")
    lines += ["", "Timeout means a harness budget ran out (step_limit, reply_limit, context_limit) or a model "
              "request timed out (request_timeout)."]
    excluded = report["excluded_infrastructure_attempts"]
    one = report["one_side_only"]
    um = report["not_compared_suites"]
    if excluded or one["left"] or one["right"] or um["left"] or um["right"]:
        lines += ["", "## Not compared", ""]
        for e in excluded:
            lines.append(f"- {e['suite']}/{e['task']}#{e['sample']}: infrastructure error excluded on both sides "
                         f"({left} {e['left']}, {right} {e['right']})")
        for side, name in (("left", left), ("right", right)):
            if one[side]:
                lines.append(f"- recorded only in {name}: {', '.join(one[side][:40])}"
                             + (f" and {len(one[side]) - 40} more" if len(one[side]) > 40 else ""))
            if um[side]:
                lines.append(f"- suites only in {name}: {', '.join(um[side])}")
    lines += ["", "Repetitions share tasks and are not independent samples. Compare a gap with the spread "
              "between two runs of the same model and setup before reading it as an effect. This report does "
              "not run inference and does not choose a winner.", ""]
    return "\n".join(lines)


__all__ = ["classify_stop", "compare_runs", "load_run", "markdown", "parse_attempts", "parse_header",
           "parse_server_log", "parse_setup_pairs"]
