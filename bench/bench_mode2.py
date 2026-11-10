"""
bench/bench_mode2.py
Mode 2 Metrics Benchmark (Tier 5)

Measures:
  M6 — Legit client success rate under ±45s clock drift (target: >99.9%)
  M7 — Replay attack rejection rate (target: 100%)

Requires: docker compose up with MODE2_ENABLED=true
          docker compose --profile mode2 up (to start Redis)

Usage:
  python bench_mode2.py --gateway http://gateway:8080
  python bench_mode2.py --gateway http://localhost:8080  (from host)
"""
import argparse
import asyncio
import hashlib
import hmac as _hmac
import json
import math
import os
import platform
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass, field, asdict
from typing import List

import httpx


# ── Inline SDK (avoids sys.path manipulation in bench container) ──────────────
def _derive_mac16(secret: str, interval: int) -> str:
    msg = f"route:{interval}".encode()
    return _hmac.new(secret.encode(), msg, hashlib.sha256).hexdigest()[:16]


def _current_interval(interval_sec: int, offset: float = 0.0) -> int:
    return math.floor((time.time() + offset) / interval_sec)


def _route_url(base: str, path: str, secret: str, interval_sec: int,
               offset: float = 0.0):
    interval = _current_interval(interval_sec, offset)
    mac = _derive_mac16(secret, interval)
    canon = path if path.startswith("/") else "/" + path
    return f"{base.rstrip('/')}/m/{interval}-{mac}{canon}", interval


def _sign(secret: str, method: str, path: str, body: bytes,
          device_id: str, nonce: str = None, timestamp: str = None) -> dict:
    if nonce is None:
        nonce = uuid.uuid4().hex
    if timestamp is None:
        timestamp = str(int(time.time()))
    body_sha = hashlib.sha256(body or b"").hexdigest()
    msg = f"{method}|{path}|{body_sha}|{timestamp}|{nonce}"
    sig = _hmac.new(secret.encode(), msg.encode(), hashlib.sha256).hexdigest()
    return {
        "X-Device-ID": device_id,
        "X-Timestamp": timestamp,
        "X-Nonce":     nonce,
        "X-Signature": sig,
        "User-Agent":  "tcad-bench-mode2/1.0",
    }


@dataclass
class Mode2BenchResults:
    date: str = ""
    hardware: str = ""
    commit_hash: str = ""
    gateway_url: str = ""
    mode2_enabled: bool = True
    interval_sec: int = 30
    grace: int = 1
    # M6
    m6_total_requests: int = 0
    m6_success_count: int = 0
    m6_failure_count: int = 0
    m6_success_rate_pct: float = 0.0
    m6_drift_offsets: List[int] = field(default_factory=list)
    # M7
    m7_replay_attempts: int = 0
    m7_replays_rejected: int = 0
    m7_rejection_rate_pct: float = 0.0
    errors: List[str] = field(default_factory=list)


async def measure_m6(args, results: Mode2BenchResults):
    """M6: legit client success under ±45s clock drift."""
    print("[M6] Measuring legit success rate under clock drift…")
    secret = args.mode2_secret
    interval_sec = args.interval_sec
    PATHS = ["/api/v1/shipments", "/api/v1/manifests", "/api/v1/routes", "/health"]
    # Systematic drift offsets from -44 to +44 in steps of 11
    drifts = list(range(-44, 45, 11))  # [-44,-33,-22,-11,0,11,22,33,44]
    results.m6_drift_offsets = drifts

    async with httpx.AsyncClient(timeout=10.0) as client:
        for drift in drifts:
            for path in PATHS:
                device_id = f"bench-m6-d{drift}-{uuid.uuid4().hex[:6]}"
                try:
                    url, _ = _route_url(args.gateway, path, secret, interval_sec, drift)
                    headers = _sign(secret, "GET", path, b"", device_id)
                    r = await client.get(url, headers=headers)
                    results.m6_total_requests += 1
                    if 200 <= r.status_code < 300:
                        results.m6_success_count += 1
                    else:
                        results.m6_failure_count += 1
                        results.errors.append(
                            f"M6 drift={drift:+d}s {path} → {r.status_code}"
                        )
                except Exception as exc:
                    results.m6_total_requests += 1
                    results.m6_failure_count += 1
                    results.errors.append(f"M6 drift={drift:+d}s {path}: {exc}")
                await asyncio.sleep(0.03)

    total = results.m6_total_requests
    results.m6_success_rate_pct = round(
        results.m6_success_count / total * 100, 2) if total else 0.0
    print(f"  total={total}  success={results.m6_success_count}  "
          f"M6={results.m6_success_rate_pct}%")


async def measure_m7(args, results: Mode2BenchResults):
    """M7: replay attack rejection rate."""
    print("[M7] Measuring replay rejection rate…")
    secret = args.mode2_secret
    interval_sec = args.interval_sec
    path = "/api/v1/shipments"

    async with httpx.AsyncClient(timeout=10.0) as client:
        # Make N fresh legitimate requests, then replay each one
        N = 5
        captured = []
        for i in range(N):
            device_id = f"bench-m7-legit-{i}-{uuid.uuid4().hex[:4]}"
            url, _ = _route_url(args.gateway, path, secret, interval_sec, 0)
            headers = _sign(secret, "GET", path, b"", device_id)
            try:
                r = await client.get(url, headers=headers)
                if 200 <= r.status_code < 300:
                    captured.append((url, headers))
                else:
                    results.errors.append(f"M7 fresh #{i} failed: {r.status_code}")
            except Exception as exc:
                results.errors.append(f"M7 fresh #{i}: {exc}")
            await asyncio.sleep(0.05)

        # Now replay each captured request 2 times
        for url, headers in captured:
            for replay_n in range(2):
                results.m7_replay_attempts += 1
                try:
                    r = await client.get(url, headers=headers)
                    if r.status_code == 401:
                        results.m7_replays_rejected += 1
                    else:
                        results.errors.append(
                            f"M7 replay not rejected: {r.status_code}"
                        )
                except Exception as exc:
                    results.errors.append(f"M7 replay attempt: {exc}")
                await asyncio.sleep(0.05)

    total = results.m7_replay_attempts
    results.m7_rejection_rate_pct = round(
        results.m7_replays_rejected / total * 100, 2) if total else 0.0
    print(f"  replay_attempts={total}  rejected={results.m7_replays_rejected}  "
          f"M7={results.m7_rejection_rate_pct}%")


async def main():
    parser = argparse.ArgumentParser(description="TCAD Mesh Mode 2 benchmark")
    parser.add_argument("--gateway",       default=os.environ.get("GATEWAY_URL",   "http://localhost:8080"))
    parser.add_argument("--out",           default=os.environ.get("RESULTS_PATH",  "results/bench_mode2.json"))
    parser.add_argument("--mode2-secret",  default=os.environ.get("MODE2_SECRET",  "change-me-mode2-secret"))
    parser.add_argument("--interval-sec",  type=int, default=int(os.environ.get("MODE2_INTERVAL_SEC", "30")))
    parser.add_argument("--grace",         type=int, default=int(os.environ.get("MODE2_GRACE", "1")))
    args = parser.parse_args()

    # Verify gateway + Mode 2 is reachable
    try:
        async with httpx.AsyncClient(timeout=5.0) as c:
            r = await c.get(f"{args.gateway}/health")
            print(f"[bench_mode2] Gateway: {r.status_code} — {r.json()}")
    except Exception as exc:
        print(f"ERROR: cannot reach gateway: {exc}", file=sys.stderr)
        sys.exit(1)

    results = Mode2BenchResults()
    results.date         = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    results.hardware     = f"{platform.system()} {platform.machine()} cores={os.cpu_count()}"
    results.gateway_url  = args.gateway
    results.mode2_enabled= True
    results.interval_sec = args.interval_sec
    results.grace        = args.grace

    try:
        commit = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            stderr=subprocess.DEVNULL,
        ).decode().strip()
    except Exception:
        commit = "pre-init"
    results.commit_hash = commit

    await measure_m6(args, results)
    await measure_m7(args, results)

    out = asdict(results)
    os.makedirs(os.path.dirname(args.out) if os.path.dirname(args.out) else ".", exist_ok=True)
    with open(args.out, "w") as f:
        json.dump(out, f, indent=2)
    print(f"\n[bench_mode2] Results → {args.out}")
    print(json.dumps(out, indent=2))

    issues = []
    if results.m6_success_rate_pct < 99.9:
        issues.append(f"M6={results.m6_success_rate_pct}% < 99.9%")
    if results.m7_rejection_rate_pct < 100.0:
        issues.append(f"M7={results.m7_rejection_rate_pct}% < 100%")
    if issues:
        print("\n[bench_mode2] GATE FAILURES:", *issues, sep="\n  ❌  ")
        sys.exit(1)
    print("\n[bench_mode2] ✅  All Mode 2 gate metrics pass")
    return out


if __name__ == "__main__":
    asyncio.run(main())
