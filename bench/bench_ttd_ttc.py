"""
bench/bench_ttd_ttc.py
Sequential TTD/TTC measurement with DB reset before each batch.

Rules per AGENTS.md Section 8:
- Run repetitions sequentially (one at a time, no concurrent load)
- Reset DB via POST /reset before each batch
- Do NOT exclude failures — report N_success/N_total
- Investigate failures using gateway logs and event timestamps
- Report honest statistics

TTD definition: wall-clock ms from the moment the canary request is sent
to the moment a CANARY_HIT event with this device_id appears in GET /events.

TTC definition: wall-clock ms from the moment the canary request is sent
to the moment a follow-up request returns a response whose JSON body contains
a honeytoken DOC-* ID that is NOT in the real target-app dataset — confirming
the identity is quarantined and the honeypot is serving the response.
"""
import asyncio
import json
import os
import platform
import statistics
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass, field, asdict
from typing import List, Optional

import httpx

REAL_IDS = {
    "DOC-1a2b3c4d5e6f", "DOC-2b3c4d5e6f7a",
    "DOC-3c4d5e6f7a8b", "DOC-4d5e6f7a8b9c",
    "DOC-5e6f7a8b9c0d",
}

POLL_INTERVAL_S = 0.1   # polling interval for event checks
MAX_POLL_S      = 10.0  # maximum time to wait per measurement


@dataclass
class Measurement:
    rep: int
    device_id: str
    success: bool
    ms: Optional[float]     # None on timeout/error
    failure_reason: str = ""
    canary_sent_at: str = ""
    event_ts_from_db: str = ""
    ttc_follow_up_latency_ms: float = 0.0   # time the follow-up request itself took


@dataclass
class BenchTTDTTCResults:
    date: str = ""
    hardware: str = ""
    commit_hash: str = ""
    gateway_url: str = ""
    ctrl_url: str = ""
    ttd: List[dict] = field(default_factory=list)
    ttc: List[dict] = field(default_factory=list)
    ttd_success: int = 0
    ttd_total: int = 0
    ttc_success: int = 0
    ttc_total: int = 0
    ttd_mean_ms: float = 0.0
    ttd_median_ms: float = 0.0
    ttd_p95_ms: float = 0.0
    ttd_min_ms: float = 0.0
    ttd_max_ms: float = 0.0
    ttc_mean_ms: float = 0.0
    ttc_median_ms: float = 0.0
    ttc_p95_ms: float = 0.0
    ttc_min_ms: float = 0.0
    ttc_max_ms: float = 0.0


def pct(values: list, p: float) -> float:
    if not values: return 0.0
    s = sorted(values)
    idx = max(0, min(len(s)-1, int(len(s)*p/100)))
    return round(s[idx], 2)


async def reset_db(ctrl: str, ikey: str) -> None:
    async with httpx.AsyncClient(base_url=ctrl, timeout=5.0) as c:
        await c.post("/reset", headers={"X-Internal-Key": ikey})


async def measure_ttd(gateway: str, ctrl: str, rep: int) -> Measurement:
    """Measure TTD: canary hit → CANARY_HIT event visible in control-api."""
    device_id = f"ttd-{rep}-{uuid.uuid4().hex[:8]}"
    m = Measurement(rep=rep, device_id=device_id, success=False, ms=None)

    t_send = time.monotonic()
    m.canary_sent_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    # Send canary request
    async with httpx.AsyncClient(base_url=gateway, timeout=10.0,
                                  headers={"X-Device-ID": device_id}) as c:
        try:
            await c.get("/admin")
        except Exception as e:
            m.failure_reason = f"canary request failed: {e}"
            return m

    # Poll for CANARY_HIT event in control-api
    deadline = t_send + MAX_POLL_S
    while time.monotonic() < deadline:
        await asyncio.sleep(POLL_INTERVAL_S)
        async with httpx.AsyncClient(base_url=ctrl, timeout=3.0) as c:
            try:
                r = await c.get(f"/events?type=CANARY_HIT&limit=200")
                for ev in r.json().get("data", []):
                    if device_id in str(ev.get("identity", "")):
                        m.success = True
                        m.ms = round((time.monotonic() - t_send) * 1000, 2)
                        m.event_ts_from_db = ev.get("ts", "")
                        return m
            except Exception:
                pass

    m.failure_reason = f"timeout after {MAX_POLL_S}s — no CANARY_HIT event found for {device_id}"
    return m


async def measure_ttc(gateway: str, rep: int) -> Measurement:
    """Measure TTC: canary hit → follow-up request routed to honeypot confirmed."""
    device_id = f"ttc-{rep}-{uuid.uuid4().hex[:8]}"
    m = Measurement(rep=rep, device_id=device_id, success=False, ms=None)

    t_send = time.monotonic()
    m.canary_sent_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    # Send canary request
    async with httpx.AsyncClient(base_url=gateway, timeout=10.0,
                                  headers={"X-Device-ID": device_id}) as c:
        try:
            await c.get("/admin")
        except Exception as e:
            m.failure_reason = f"canary request failed: {e}"
            return m

    # Poll with follow-up requests; detect when response contains honeytoken IDs
    deadline = t_send + MAX_POLL_S
    while time.monotonic() < deadline:
        await asyncio.sleep(POLL_INTERVAL_S)
        t_follow = time.monotonic()
        async with httpx.AsyncClient(base_url=gateway, timeout=5.0,
                                      headers={"X-Device-ID": device_id}) as c:
            try:
                r = await c.get("/api/v1/shipments")
                follow_ms = round((time.monotonic() - t_follow) * 1000, 2)
                if r.status_code == 200:
                    data = r.json().get("data", [])
                    if data:
                        token = data[0].get("id", "")
                        if token and token not in REAL_IDS:
                            # Response contains a honeytoken → quarantined + honeypot confirmed
                            m.success = True
                            m.ms = round((time.monotonic() - t_send) * 1000, 2)
                            m.ttc_follow_up_latency_ms = follow_ms
                            return m
            except Exception:
                pass

    m.failure_reason = (
        f"timeout after {MAX_POLL_S}s — follow-up never returned honeypot data for {device_id}"
    )
    return m


async def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--gateway", default=os.environ.get("GATEWAY_URL", "http://gateway:8080"))
    parser.add_argument("--ctrl",   default=os.environ.get("CONTROL_URL", "http://control-api:8003"))
    parser.add_argument("--ikey",   default=os.environ.get("INTERNAL_KEY", "change-me"))
    parser.add_argument("--n",      type=int, default=30)
    parser.add_argument("--out",    default="results/bench_ttd_ttc.json")
    args = parser.parse_args()

    print(f"[ttd_ttc] Sequential TTD/TTC benchmark  n={args.n}")
    print(f"  gateway={args.gateway}  ctrl={args.ctrl}")
    print(f"  max_poll={MAX_POLL_S}s  poll_interval={POLL_INTERVAL_S}s")
    print()

    results = BenchTTDTTCResults()
    results.date = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    results.hardware = f"{platform.system()} {platform.machine()} cores={os.cpu_count()}"
    results.gateway_url = args.gateway
    results.ctrl_url = args.ctrl
    try:
        results.commit_hash = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"], stderr=subprocess.DEVNULL
        ).decode().strip()
    except Exception:
        results.commit_hash = "pre-init"

    # ── TTD batch ──────────────────────────────────────────────
    print("=== TTD measurements (sequential, DB reset before batch) ===")
    await reset_db(args.ctrl, args.ikey)
    print(f"  DB reset. Starting {args.n} sequential reps…")
    await asyncio.sleep(1)

    for rep in range(1, args.n + 1):
        m = await measure_ttd(args.gateway, args.ctrl, rep)
        status = f"{m.ms}ms" if m.success else f"FAILED: {m.failure_reason}"
        print(f"  rep {rep:2d}/{args.n}: {status}")
        results.ttd.append(asdict(m))

    # ── TTC batch ──────────────────────────────────────────────
    print()
    print("=== TTC measurements (sequential, DB reset before batch) ===")
    await reset_db(args.ctrl, args.ikey)
    print(f"  DB reset. Starting {args.n} sequential reps…")
    await asyncio.sleep(1)

    for rep in range(1, args.n + 1):
        m = await measure_ttc(args.gateway, rep)
        status = f"{m.ms}ms" if m.success else f"FAILED: {m.failure_reason}"
        print(f"  rep {rep:2d}/{args.n}: {status}")
        results.ttc.append(asdict(m))

    # ── Statistics ─────────────────────────────────────────────
    ttd_ok  = [r["ms"] for r in results.ttd if r["success"]]
    ttc_ok  = [r["ms"] for r in results.ttc if r["success"]]
    results.ttd_success = len(ttd_ok)
    results.ttd_total   = len(results.ttd)
    results.ttc_success = len(ttc_ok)
    results.ttc_total   = len(results.ttc)

    if ttd_ok:
        results.ttd_mean_ms   = round(statistics.mean(ttd_ok), 2)
        results.ttd_median_ms = round(statistics.median(ttd_ok), 2)
        results.ttd_p95_ms    = pct(ttd_ok, 95)
        results.ttd_min_ms    = round(min(ttd_ok), 2)
        results.ttd_max_ms    = round(max(ttd_ok), 2)

    if ttc_ok:
        results.ttc_mean_ms   = round(statistics.mean(ttc_ok), 2)
        results.ttc_median_ms = round(statistics.median(ttc_ok), 2)
        results.ttc_p95_ms    = pct(ttc_ok, 95)
        results.ttc_min_ms    = round(min(ttc_ok), 2)
        results.ttc_max_ms    = round(max(ttc_ok), 2)

    # Save
    os.makedirs(os.path.dirname(args.out) if os.path.dirname(args.out) else ".", exist_ok=True)
    with open(args.out, "w") as f:
        json.dump(asdict(results), f, indent=2)

    # Print summary
    print()
    print("=== TTD Summary ===")
    print(f"  N={results.ttd_success}/{results.ttd_total} succeeded")
    if ttd_ok:
        print(f"  mean={results.ttd_mean_ms}ms  median={results.ttd_median_ms}ms"
              f"  p95={results.ttd_p95_ms}ms  min={results.ttd_min_ms}ms  max={results.ttd_max_ms}ms")
    for r in results.ttd:
        if not r["success"]:
            print(f"  FAILURE rep {r['rep']}: {r['failure_reason']}")

    print()
    print("=== TTC Summary ===")
    print(f"  N={results.ttc_success}/{results.ttc_total} succeeded")
    if ttc_ok:
        print(f"  mean={results.ttc_mean_ms}ms  median={results.ttc_median_ms}ms"
              f"  p95={results.ttc_p95_ms}ms  min={results.ttc_min_ms}ms  max={results.ttc_max_ms}ms")
    for r in results.ttc:
        if not r["success"]:
            print(f"  FAILURE rep {r['rep']}: {r['failure_reason']}")

    print(f"\n[ttd_ttc] Results saved → {args.out}")


if __name__ == "__main__":
    asyncio.run(main())
