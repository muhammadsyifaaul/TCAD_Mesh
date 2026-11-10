"""
bench/bench_network.py
In-network latency benchmark.

Runs inside the Docker mesh network (via docker compose run --rm bench ...)
and measures latency at 100, 250, and 500 req/s through the gateway
AND directly to target-app (bypassing the gateway).

Measures p50/p95/p99 for each rate and each path.

Usage (inside Docker network):
  docker compose run --rm bench python bench_network.py

Usage (from host, proxying control-api via dashboard):
  python bench/bench_network.py --gateway http://localhost:8080
"""
import argparse
import asyncio
import json
import os
import platform
import subprocess
import sys
import time
from dataclasses import dataclass, field, asdict
from typing import List

import httpx


def percentile(values: list, pct: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    idx = max(0, min(len(s) - 1, int(len(s) * pct / 100)))
    return round(s[idx] * 1000, 2)  # s → ms


@dataclass
class RateResult:
    target: str       # "gateway" or "upstream"
    target_rps: int
    actual_rps: float
    total_requests: int
    success: int
    failures: int
    p50_ms: float
    p95_ms: float
    p99_ms: float
    latencies_ms: List[float] = field(default_factory=list)


@dataclass
class NetworkBenchResults:
    date: str = ""
    hardware: str = ""
    commit_hash: str = ""
    gateway_url: str = ""
    upstream_url: str = ""
    results: List[dict] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)


async def measure_rate(client: httpx.AsyncClient, path: str,
                        target_rps: int, duration_sec: float = 2.0) -> RateResult:
    """Send requests at approximately target_rps for duration_sec seconds."""
    latencies = []
    total = 0
    success = 0
    failures = 0

    interval = 1.0 / target_rps if target_rps > 0 else 0
    sem = asyncio.Semaphore(100)  # cap concurrency

    async def single_request():
        nonlocal total, success, failures
        async with sem:
            t0 = time.monotonic()
            try:
                r = await client.get(path)
                elapsed = time.monotonic() - t0
                total += 1
                if 200 <= r.status_code < 300:
                    success += 1
                    latencies.append(elapsed)
                else:
                    failures += 1
            except Exception:
                total += 1
                failures += 1

    t_start = time.monotonic()
    tasks = []
    n_requests = int(target_rps * duration_sec)

    for i in range(n_requests):
        tasks.append(asyncio.create_task(single_request()))
        if interval > 0:
            await asyncio.sleep(interval)

    await asyncio.gather(*tasks)
    elapsed = time.monotonic() - t_start

    actual_rps = round(total / elapsed, 1) if elapsed > 0 else 0

    return RateResult(
        target="",
        target_rps=target_rps,
        actual_rps=actual_rps,
        total_requests=total,
        success=success,
        failures=failures,
        p50_ms=percentile(latencies, 50),
        p95_ms=percentile(latencies, 95),
        p99_ms=percentile(latencies, 99),
        latencies_ms=[],  # don't store all raw latencies in the JSON
    )


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--gateway",  default=os.environ.get("GATEWAY_URL",  "http://gateway:8080"))
    parser.add_argument("--upstream", default=os.environ.get("UPSTREAM_URL", "http://target-app:8001"))
    parser.add_argument("--out",      default=os.environ.get("RESULTS_PATH", "/results/bench_network.json"))
    args = parser.parse_args()

    print(f"[bench_network] gateway={args.gateway}  upstream={args.upstream}")
    print()

    results = NetworkBenchResults()
    results.date = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    results.hardware = f"{platform.system()} {platform.machine()} cores={os.cpu_count()}"
    try:
        results.commit_hash = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            stderr=subprocess.DEVNULL
        ).decode().strip()
    except Exception:
        results.commit_hash = "pre-init"
    results.gateway_url = args.gateway
    results.upstream_url = args.upstream

    PATH = "/api/v1/shipments"
    RATES = [100, 250, 500]

    # ── Through the gateway ──────────────────────────────────────────────────
    print("=== Through Gateway ===")
    async with httpx.AsyncClient(base_url=args.gateway, timeout=10.0,
                                  headers={"X-Device-ID": "bench-net-gw"}) as gw_client:
        for rate in RATES:
            print(f"  {rate} req/s ...", end="", flush=True)
            r = await measure_rate(gw_client, PATH, rate)
            r.target = "gateway"
            print(f" actual={r.actual_rps} rps  p50={r.p50_ms}ms  p95={r.p95_ms}ms  p99={r.p99_ms}ms"
                  f"  ok={r.success}/{r.total_requests}")
            results.results.append(asdict(r))

    # ── Direct to upstream (target-app) ──────────────────────────────────────
    print("\n=== Direct to Upstream (target-app) ===")
    async with httpx.AsyncClient(base_url=args.upstream, timeout=10.0) as up_client:
        for rate in RATES:
            print(f"  {rate} req/s ...", end="", flush=True)
            r = await measure_rate(up_client, PATH, rate)
            r.target = "upstream"
            print(f" actual={r.actual_rps} rps  p50={r.p50_ms}ms  p95={r.p95_ms}ms  p99={r.p99_ms}ms"
                  f"  ok={r.success}/{r.total_requests}")
            results.results.append(asdict(r))

    # ── Gateway overhead at each rate ────────────────────────────────────────
    print("\n=== Gateway Overhead (gateway_p50 - upstream_p50) ===")
    for rate in RATES:
        gw_p50 = next((r["p50_ms"] for r in results.results
                       if r["target"] == "gateway" and r["target_rps"] == rate), 0)
        up_p50 = next((r["p50_ms"] for r in results.results
                       if r["target"] == "upstream" and r["target_rps"] == rate), 0)
        overhead = round(gw_p50 - up_p50, 2)
        print(f"  {rate} req/s: gateway={gw_p50}ms  upstream={up_p50}ms  overhead={overhead}ms")

    # Save
    out_dict = asdict(results)
    out_dir = os.path.dirname(args.out) if os.path.dirname(args.out) else "."
    os.makedirs(out_dir, exist_ok=True)
    with open(args.out, "w") as f:
        json.dump(out_dict, f, indent=2)
    print(f"\n[bench_network] Results saved → {args.out}")


if __name__ == "__main__":
    asyncio.run(main())
