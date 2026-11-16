"""Hardware auto-detection and edge inference server profiler (stdlib only)."""

import concurrent.futures
import hashlib
import json
import os
import platform
import re
import shutil
import statistics
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from .results import identifier, integer, require


def _read_text(path):
    try:
        return Path(path).read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return None


def _detect_cpu():
    model = None
    cpuinfo = _read_text("/proc/cpuinfo")
    if cpuinfo:
        for line in cpuinfo.splitlines():
            if line.lower().startswith("model name"):
                _, _, value = line.partition(":")
                model = value.strip()
                break
    if not model and platform.system() == "Darwin":
        sysctl = shutil.which("sysctl")
        if sysctl:
            res = subprocess.run([sysctl, "-n", "machdep.cpu.brand_string"],
                                 capture_output=True, text=True, timeout=2)
            if res.returncode == 0 and res.stdout.strip():
                model = res.stdout.strip()
    if not model:
        model = platform.processor() or platform.machine() or "unknown"
    return model


def _detect_memory_gb():
    meminfo = _read_text("/proc/meminfo")
    total_gb = avail_gb = None
    if meminfo:
        for line in meminfo.splitlines():
            parts = line.split()
            if len(parts) >= 2 and parts[1].isdigit():
                gb = round(int(parts[1]) / (1024 * 1024), 2)
                if parts[0] == "MemTotal:":
                    total_gb = gb
                elif parts[0] == "MemAvailable:":
                    avail_gb = gb
    elif platform.system() == "Darwin":
        sysctl = shutil.which("sysctl")
        if sysctl:
            res = subprocess.run([sysctl, "-n", "hw.memsize"],
                                 capture_output=True, text=True, timeout=2)
            if res.returncode == 0 and res.stdout.strip().isdigit():
                total_gb = round(int(res.stdout.strip()) / (1024 ** 3), 2)
    return total_gb, avail_gb


def _detect_accelerators():
    devices = []
    nvidia_smi = shutil.which("nvidia-smi")
    if nvidia_smi:
        try:
            res = subprocess.run(
                [nvidia_smi, "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"],
                capture_output=True, text=True, timeout=3,
            )
            if res.returncode == 0:
                for line in res.stdout.splitlines():
                    if "," in line:
                        name, _, mem_mb = line.partition(",")
                        mem_gb = round(float(mem_mb.strip()) / 1024.0, 2) if mem_mb.strip().replace(".", "", 1).isdigit() else None
                        devices.append({"backend": "cuda", "name": name.strip(), "vram_gb": mem_gb})
        except (OSError, subprocess.SubprocessError, ValueError):
            pass

    if not devices:
        drm = Path("/sys/class/drm")
        vram_gb = gtt_gb = None
        if drm.is_dir():
            for card in sorted(drm.glob("card[0-9]*")):
                vram_raw = _read_text(card / "device/mem_info_vram_total")
                gtt_raw = _read_text(card / "device/mem_info_gtt_total")
                if vram_raw and vram_raw.isdigit() and int(vram_raw) > 0:
                    vram_gb = round(int(vram_raw) / (1024 ** 3), 2)
                    if gtt_raw and gtt_raw.isdigit() and int(gtt_raw) > 0:
                        gtt_gb = round(int(gtt_raw) / (1024 ** 3), 2)
                    break
        vulkaninfo = shutil.which("vulkaninfo")
        if vulkaninfo:
            try:
                res = subprocess.run([vulkaninfo, "--summary"], capture_output=True, text=True, timeout=4)
                if res.returncode == 0:
                    for line in res.stdout.splitlines():
                        match = re.search(r"deviceName\s*=\s*(.+)", line)
                        if match:
                            name = match.group(1).strip()
                            if "llvmpipe" not in name.lower():
                                entry = {"backend": "vulkan", "name": name, "vram_gb": vram_gb}
                                if gtt_gb is not None:
                                    entry["gtt_gb"] = gtt_gb
                                devices.append(entry)
            except (OSError, subprocess.SubprocessError):
                pass
        if not devices and vram_gb is not None:
            entry = {"backend": "amdgpu", "name": "AMD GPU", "vram_gb": vram_gb}
            if gtt_gb is not None:
                entry["gtt_gb"] = gtt_gb
            devices.append(entry)
    return devices


def _detect_thermals():
    temps = {}
    hwmon = Path("/sys/class/hwmon")
    if not hwmon.is_dir():
        return temps
    for device in sorted(hwmon.glob("hwmon*")):
        for label_path in sorted(device.glob("temp*_label")):
            label = _read_text(label_path)
            if label in ("Tctl", "Package id 0", "edge"):
                val = _read_text(label_path.with_name(label_path.name.replace("_label", "_input")))
                if val and val.lstrip("-").isdigit():
                    temps[label] = round(int(val) / 1000.0, 1)
    return temps


def detect_hardware():
    """Auto-detect local CPU, memory, accelerators, and thermal readings."""
    cpu_model = _detect_cpu()
    ram_total_gb, ram_avail_gb = _detect_memory_gb()
    accelerators = _detect_accelerators()
    thermals = _detect_thermals()
    if accelerators:
        primary = accelerators[0]
        if primary.get("gtt_gb") and (primary.get("vram_gb") or 0) <= 2.0:
            device_label = f"{primary['name']} (Unified {primary['gtt_gb']} GB)"
        elif primary.get("vram_gb"):
            device_label = f"{primary['name']} ({primary['vram_gb']} GB)"
        else:
            device_label = f"{primary['name']} (Unified {ram_total_gb} GB)" if ram_total_gb else primary["name"]
    else:
        device_label = f"{cpu_model} (CPU · {ram_total_gb} GB)" if ram_total_gb else cpu_model
    return {
        "os": platform.system(),
        "arch": platform.machine(),
        "cpu_model": cpu_model,
        "cpu_logical_cores": os.cpu_count(),
        "ram_total_gb": ram_total_gb,
        "ram_available_gb": ram_avail_gb,
        "accelerators": accelerators,
        "thermals_c": thermals,
        "device_label": device_label,
    }


def _validate_base_url(base_url):
    url = urllib.parse.urlsplit(base_url)
    require(url.scheme in ("http", "https") and url.hostname and not url.username
            and not url.password and not url.query and not url.fragment,
            "invalid server base_url")
    return base_url.rstrip("/")


def _http_json(url, headers=None, timeout=5):
    req = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read(2 * 1024 * 1024).decode("utf-8"))


def _probe_single_stream(chat_url, model, headers, prompt, max_tokens, timeout):
    body = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
        "temperature": 0.0,
        "seed": 1,
        "stream": True,
        "stream_options": {"include_usage": True},
    }
    req = urllib.request.Request(
        chat_url,
        data=json.dumps(body).encode("utf-8"),
        headers={**headers, "Content-Type": "application/json"},
    )
    t_start = time.monotonic()
    t_first = None
    chunk_tokens = 0
    prompt_tokens = None
    completion_tokens = None
    event = []
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        ctype = resp.headers.get("Content-Type", "").lower()
        if "text/event-stream" not in ctype:
            data = json.loads(resp.read(2 * 1024 * 1024).decode("utf-8"))
            t_end = time.monotonic()
            usage = data.get("usage") or {}
            completion_tokens = usage.get("completion_tokens")
            prompt_tokens = usage.get("prompt_tokens")
            elapsed = max(1e-6, t_end - t_start)
            return {
                "ttft_seconds": elapsed,
                "decode_seconds": elapsed,
                "total_seconds": elapsed,
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "decode_tok_s": (completion_tokens / elapsed) if completion_tokens else None,
            }
        while True:
            raw_line = resp.readline(1024 * 1024)
            if not raw_line:
                break
            line = raw_line.decode("utf-8", errors="replace").rstrip("\r\n")
            if line.startswith("data:"):
                event.append(line[5:].lstrip(" "))
                continue
            if line or not event:
                continue
            payload = "\n".join(event)
            event = []
            if payload == "[DONE]":
                break
            chunk = json.loads(payload)
            if isinstance(chunk, dict) and chunk.get("usage"):
                usage = chunk["usage"]
                if isinstance(usage.get("prompt_tokens"), int):
                    prompt_tokens = usage["prompt_tokens"]
                if isinstance(usage.get("completion_tokens"), int):
                    completion_tokens = usage["completion_tokens"]
            choices = chunk.get("choices") if isinstance(chunk, dict) else None
            if isinstance(choices, list) and choices:
                delta = choices[0].get("delta") or {}
                has_token = bool(delta.get("content") or delta.get("reasoning_content") or delta.get("tool_calls"))
                if has_token:
                    if t_first is None:
                        t_first = time.monotonic()
                    chunk_tokens += 1
    t_end = time.monotonic()
    if t_first is None:
        t_first = t_end
    ttft = max(1e-6, t_first - t_start)
    decode_sec = max(1e-6, t_end - t_first)
    out_tok = completion_tokens if isinstance(completion_tokens, int) and completion_tokens > 0 else chunk_tokens
    return {
        "ttft_seconds": ttft,
        "decode_seconds": decode_sec,
        "total_seconds": max(1e-6, t_end - t_start),
        "prompt_tokens": prompt_tokens,
        "completion_tokens": out_tok if out_tok > 0 else None,
        "decode_tok_s": (out_tok / decode_sec) if out_tok > 0 and decode_sec > 0 else None,
    }


def _extract_server_metadata(base_url, headers, timeout=5):
    """Fetch non-sensitive server capabilities from /props, /slots, /models if supported."""
    meta = {"max_context_tokens": None, "slots": None, "model_alias": None, "offload": None}
    root = base_url[:-3] if base_url.endswith("/v1") else base_url
    for suffix in ("/props", "/slots"):
        try:
            data = _http_json(root + suffix, headers=headers, timeout=timeout)
            if suffix == "/props" and isinstance(data, dict):
                gen = data.get("default_generation_settings") or {}
                if isinstance(gen.get("n_ctx"), int) and gen["n_ctx"] > 0:
                    meta["max_context_tokens"] = gen["n_ctx"]
                if isinstance(data.get("total_slots"), int) and data["total_slots"] > 0:
                    meta["slots"] = data["total_slots"]
                if isinstance(data.get("model_alias"), str):
                    meta["model_alias"] = data["model_alias"]
            elif suffix == "/slots" and isinstance(data, list) and data:
                meta["slots"] = len(data)
                if isinstance(data[0], dict) and isinstance(data[0].get("n_ctx"), int):
                    meta["max_context_tokens"] = meta["max_context_tokens"] or data[0]["n_ctx"]
        except urllib.error.HTTPError as err:
            err.close()
        except (OSError, urllib.error.URLError, ValueError, TimeoutError):
            pass
    return meta


def probe_server(
    base_url,
    model,
    api_key=None,
    streams=(1, 4),
    prompt_words=180,
    max_tokens=48,
    timeout=60,
    probe_fn=None,
    server_meta_fn=None,
):
    """Measure local/edge inference TTFT and 1->N stream throughput without inventing metrics."""
    base = _validate_base_url(base_url)
    require(isinstance(model, str) and model, "model required")
    require(isinstance(streams, (list, tuple)) and streams and all(integer(s, 1) and s <= 32 for s in streams),
            "invalid stream counts")
    streams = sorted(set(streams))
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    chat_url = base + "/chat/completions"
    prompt = ("Summarize the key edge-AI inference bottleneck when serving concurrent local "
              "subagent streams on unified memory. " * ((prompt_words // 15) + 1))[:prompt_words * 6]

    meta_fn = server_meta_fn or _extract_server_metadata
    server_meta = meta_fn(base, headers, min(timeout, 5))
    runner = probe_fn or _probe_single_stream

    stream_results = {}
    for count in streams:
        t0 = time.monotonic()
        with concurrent.futures.ThreadPoolExecutor(max_workers=count) as pool:
            futures = [
                pool.submit(runner, chat_url, model, headers, prompt, max_tokens, timeout)
                for _ in range(count)
            ]
            runs = [f.result() for f in futures]
        wall = max(1e-6, time.monotonic() - t0)
        ttfts = [r["ttft_seconds"] for r in runs if r.get("ttft_seconds") is not None]
        tok_rates = [r["decode_tok_s"] for r in runs if r.get("decode_tok_s") is not None]
        total_out = sum(r["completion_tokens"] for r in runs if r.get("completion_tokens") is not None)
        all_have_tokens = all(r.get("completion_tokens") is not None for r in runs)
        stream_results[count] = {
            "streams": count,
            "wall_seconds": round(wall, 4),
            "median_ttft_seconds": round(statistics.median(ttfts), 4) if ttfts else None,
            "mean_per_stream_tok_s": round(statistics.mean(tok_rates), 2) if tok_rates else None,
            "aggregate_tok_s": round(total_out / wall, 2) if all_have_tokens and total_out > 0 else None,
        }

    hw = detect_hardware()
    first_stream = stream_results[streams[0]]
    max_stream = stream_results[streams[-1]]
    edge_profile = {
        "device": hw["device_label"],
        "max_context_tokens": server_meta.get("max_context_tokens"),
        "streams_tested": max(streams),
        "speed_1_stream_tok_s": first_stream["aggregate_tok_s"] or first_stream["mean_per_stream_tok_s"],
        "speed_n_streams_tok_s": max_stream["aggregate_tok_s"] or max_stream["mean_per_stream_tok_s"],
        "ttft_seconds": first_stream["median_ttft_seconds"],
    }
    edge_profile = {k: v for k, v in edge_profile.items() if v is not None}
    doc = {
        "schema_version": 1,
        "model": model,
        "hardware": hw,
        "server": server_meta,
        "streams": {str(k): v for k, v in stream_results.items()},
        "edge_profile": edge_profile,
    }
    doc["profile_sha256"] = hashlib.sha256(
        json.dumps(doc, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()
    return doc
