"""
bench/bench_stats.py
Statistical validity benchmark.

Measures with adequate sample sizes:
  - Time-to-detect (TTD): 30+ repetitions — ms from canary hit to CANARY_HIT event
    visible in control-api. Reports mean, median, p95, min, max.
  - Time-to-contain (TTC): 30+ repetitions — ms from canary hit to quarantine
    confirmed (follow-up request routed to honeypot). Reports same stats.
  - Honeytoken attribution: 50+ honeytokens issued, then reused one at a time.
    Reports how many triggered HONEYTOKEN_REUSED events.

Definition of TTC: time from the initial canary request to the moment a
follow-up request from the same identity is confirmed routed to the honeypot
(returns 200 AND the response body contains a honeytoken ID, not a real ID).

Usage:
  python bench/bench_stats.py --gateway http://localhost:8080 --ctrl http://localhost:3000
"""
import argparse
import asyncio
import json
import os
import platform
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass, field, asdict
from typing import List
import statistics

import httpx


@dataclass
class StatsResults:
    date: str = ""
    hardware: str = ""
    commit_hash: str = ""
    # TTD
    ttd_samples_ms: List[float] = field(default_factory=list)
    ttd_mean_ms: float = 0.0
    ttd_median_ms: float = 0.0
    ttd_p95_ms: float = 0.0
    ttd_min_ms: float = 0.0
    ttd_max_ms: float = 0.0
    ttd_count: int = 0
    # TTC
    ttc_samples_ms: List[float] = field(default_factory=list)
    ttc_mean_ms: float = 0.0
    ttc_median_ms: float = 0.0
    ttc_p95_ms: float = 0.0
    ttc_min_ms: float = 0.0
    ttc_max_ms: float = 0.0
    ttc_count: int = 0
    # Honeytoken attribution
    ht_tokens_issued: int = 0
    ht_tokens_reused: int = 0
    ht_attribution_rate_pct: float = 0.0
    errors: List[str] = field(default_factory=list)


def percentile(values: list, pct: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    idx = max(0, min(len(s) - 1, int(len(s) * pct / 100)))
    return round(s[idx], 2)


async def measure_ttd_once(gateway: str, ctrl: str, device_id: str) -> float:
    """Single TTD measurement: time from canary request to CANARY_HIT event visible."""
    t0 = time.monotonic()

    async with httpx.AsyncClient(base_url=gateway, timeout=10.0,
                                  headers={"X-Device-ID": device_id}) as c:
        await c.get("/admin")

    # Poll for the event
    for _ in range(50):  # up to 5 seconds
        await asyncio.sleep(0.1)
        async with httpx.AsyncClient(base_url=ctrl, timeout=3.0) as c:
            try:
                r = await c.get(f"/events?type=CANARY_HIT&limit=20")
                for ev in r.json().get("data", []):
                    if device_id in str(ev.get("identity", "")):
                        return round((time.monotonic() - t0) * 1000, 2)
            except Exception:
                pass
    return -1.0  # timeout


async def measure_ttc_once(gateway: str, device_id: str) -> float:
    """Single TTC measurement: time from canary request to follow-up confirmed honeypot.

    TTC definition: time from the initial canary request to the moment a follow-up
    request from the same identity returns 200 with body containing a honeytoken
    (DOC-xxx ID that is NOT in the real target-app data).
    """
    t0 = time.monotonic()

    async with httpx.AsyncClient(base_url=gateway, timeout=10.0,
                                  headers={"X-Device-ID": device_id}) as c:
        # Trigger canary
        await c.get("/admin")
        # Poll with follow-up requests
        for _ in range(50):  # up to 5 seconds
            await asyncio.sleep(0.1)
            try:
                r = await c.get("/api/v1/shipments")
                if r.status_code == 200:
                    body = r.json()
                    data = body.get("data", [])
                    if data:
                        # If the first shipment ID is NOT one of the real target-app IDs,
                        # the identity is quarantined and getting honeypot data
                        token = data[0].get("id", "")
                        # Real target-app has DOC-1a2b3c4d5e6f, DOC-2b3c4d5e6f7a, etc.
                        # Honeypot IDs are HMAC-derived per identity, so they'll differ
                        # We check if the identity is quarantined by verifying
                        # the response is from honeypot (IDs won't match real data)
                        real_ids = {"DOC-1a2b3c4d5e6f", "DOC-2b3c4d5e6f7a",
                                     "DOC-3c4d5e6f7a8b", "DOC-4d5e6f7a8b9c",
                                     "DOC-5e6f7a8b9c0d"}
                        if token not in real_ids:
                            return round((time.monotonic() - t0) * 1000, 2)
            except Exception:
                pass
    return -1.0  # timeout


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--gateway", default=os.environ.get("GATEWAY_URL", "http://localhost:8080"))
    parser.add_argument("--ctrl",   default=os.environ.get("CONTROL_URL", "http://localhost:3000"))
    parser.add_argument("--out",    default="results/bench_stats.json")
    parser.add_argument("--ttd-reps",  type=int, default=30)
    parser.add_argument("--ttc-reps",  type=int, default=30)
    parser.add_argument("--ht-count",  type=int, default=50)
    args = parser.parse_args()

    print(f"[bench_stats] TTD reps={args.ttd_reps}  TTC reps={args.ttc_reps}  HT count={args.ht_count}")
    print(f"              gateway={args.gateway}  ctrl={args.ctrl}")
    print()

    results = StatsResults()
    results.date = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    results.hardware = f"{platform.system()} {platform.machine()} cores={os.cpu_count()}"
    try:
        results.commit_hash = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"], stderr=subprocess.DEVNULL
        ).decode().strip()
    except Exception:
        results.commit_hash = "pre-init"

    # ── TTD: 30+ repetitions ──────────────────────────────────────────────────
    print(f"=== TTD ({args.ttd_reps} reps) ===")
    for i in range(args.ttd_reps):
        did = f"stats-ttd-{i}-{uuid.uuid4().hex[:6]}"
        ms = await measure_ttd_once(args.gateway, args.ctrl, did)
        if ms > 0:
            results.ttd_samples_ms.append(ms)
        else:
            results.errors.append(f"TTD rep {i}: timeout")
        if (i + 1) % 10 == 0:
            print(f"  {i+1}/{args.ttd_reps} done")

    if results.ttd_samples_ms:
        results.ttd_count = len(results.ttd_samples_ms)
        results.ttd_mean_ms = round(statistics.mean(results.ttd_samples_ms), 2)
        results.ttd_median_ms = round(statistics.median(results.ttd_samples_ms), 2)
        results.ttd_p95_ms = percentile(results.ttd_samples_ms, 95)
        results.ttd_min_ms = round(min(results.ttd_samples_ms), 2)
        results.ttd_max_ms = round(max(results.ttd_samples_ms), 2)
        print(f"  mean={results.ttd_mean_ms}ms  median={results.ttd_median_ms}ms"
              f"  p95={results.ttd_p95_ms}ms  min={results.ttd_min_ms}ms  max={results.ttd_max_ms}ms"
              f"  N={results.ttd_count}")

    # ── TTC: 30+ repetitions ──────────────────────────────────────────────────
    print(f"\n=== TTC ({args.ttc_reps} reps) ===")
    for i in range(args.ttc_reps):
        did = f"stats-ttc-{i}-{uuid.uuid4().hex[:6]}"
        ms = await measure_ttc_once(args.gateway, did)
        if ms > 0:
            results.ttc_samples_ms.append(ms)
        else:
            results.errors.append(f"TTC rep {i}: timeout")
        if (i + 1) % 10 == 0:
            print(f"  {i+1}/{args.ttc_reps} done")

    if results.ttc_samples_ms:
        results.ttc_count = len(results.ttc_samples_ms)
        results.ttc_mean_ms = round(statistics.mean(results.ttc_samples_ms), 2)
        results.ttc_median_ms = round(statistics.median(results.ttc_samples_ms), 2)
        results.ttc_p95_ms = percentile(results.ttc_samples_ms, 95)
        results.ttc_min_ms = round(min(results.ttc_samples_ms), 2)
        results.ttc_max_ms = round(max(results.ttc_samples_ms), 2)
        print(f"  mean={results.ttc_mean_ms}ms  median={results.ttc_median_ms}ms"
              f"  p95={results.ttc_p95_ms}ms  min={results.ttc_min_ms}ms  max={results.ttc_max_ms}ms"
              f"  N={results.ttc_count}")

    # ── Honeytoken attribution: 50+ tokens ────────────────────────────────────
    print(f"\n=== Honeytoken Attribution ({args.ht_count} tokens) ===")
    # Step 1: Issue many honeytokens by quarantining many identities and getting honeypot data
    tokens = []
    for i in range(args.ht_count):
        did = f"stats-ht-{i}-{uuid.uuid4().hex[:6]}"
        async with httpx.AsyncClient(base_url=args.gateway, timeout=10.0,
                                       headers={"X-Device-ID": did}) as c:
            # Quarantine via canary
            await c.get("/admin")
            await asyncio.sleep(0.1)
            # Get honeypot response with honeytoken
            r = await c.get("/api/v1/shipments")
            try:
                token = r.json()["data"][0]["id"]
                tokens.append((token, did))
            except Exception:
                results.errors.append(f"HT {i}: could not extract token")

    results.ht_tokens_issued = len(tokens)
    print(f"  Issued {results.ht_tokens_issued} honeytokens")

    # Step 2: Wait for gateway to poll honeytoken list
    await asyncio.sleep(3)

    # Step 3: Reuse each token with a fresh identity
    reused_count = 0
    for token, original_id in tokens:
        reuse_id = f"stats-ht-reuse-{uuid.uuid4().hex[:6]}"
        async with httpx.AsyncClient(base_url=args.gateway, timeout=10.0,
                                       headers={"X-Device-ID": reuse_id}) as c:
            await c.get(f"/api/v1/shipments?doc={token}")

    await asyncio.sleep(3)  # let events settle

    # Step 4: Count HONEYTOKEN_REUSED events
    async with httpx.AsyncClient(base_url=args.ctrl, timeout=5.0) as c:
        try:
            r = await c.get("/events?type=HONEYTOKEN_REUSED&limit=200")
            results.ht_tokens_reused = r.json().get("total", 0)
        except Exception:
            results.errors.append("could not count HONEYTOKEN_REUSED events")

    results.ht_attribution_rate_pct = (
        round(results.ht_tokens_reused / max(1, results.ht_tokens_issued) * 100, 1)
        if results.ht_tokens_reused > 0 else 0.0
    )
    print(f"  Issued={results.ht_tokens_issued}  Reused={results.ht_tokens_reused}"
          f"  Attribution={results.ht_attribution_rate_pct}%")

    # Save
    out_dict = asdict(results)
    # Don't save all raw samples to keep file small
    out_dict["ttd_samples_ms"] = results.ttd_samples_ms[:10]  # keep first 10 as sample
    out_dict["ttc_samples_ms"] = results.ttc_samples_ms[:10]
    os.makedirs(os.path.dirname(args.out) if os.path.dirname(args.out) else ".", exist_ok=True)
    with open(args.out, "w") as f:
        json.dump(out_dict, f, indent=2)
    print(f"\n[bench_stats] Results saved → {args.out}")


if __name__ == "__main__":
    asyncio.run(main())
