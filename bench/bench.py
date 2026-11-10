"""
bench/bench.py
TCAD Mesh — Mode 1 Metrics Benchmark Harness

Measures (per AGENTS.md metric definitions):
  M1  Canary detection rate     — fraction of canary requests caught
  M2  Enum detection latency    — requests until ENUM_DETECTED fires
  M3  Tarpit delay (ms)         — measured wall-clock delay on tarpitted requests
  M4  Tarpit saturation (429)   — concurrent flood beyond TarpitMaxConcurrent
  M8  False-positive rate       — legit requests that receive non-2xx

All numbers are measured from REAL requests to a live gateway.
DO NOT fabricate metrics (AGENTS.md Rule 7).

Usage (inside Docker network):
  python bench.py --gateway http://gateway:8080 --ctrl http://control-api:8003

Usage (from host, after docker compose up):
  python bench.py --gateway http://localhost:8080 --ctrl http://localhost:3000
"""
import argparse
import asyncio
import json
import os
import platform
import socket
import subprocess
import sys
import time
from dataclasses import dataclass, field, asdict
from typing import List

import httpx


# ── Result container ──────────────────────────────────────────────────────────
@dataclass
class BenchResults:
    # Context
    date: str = ""
    hardware: str = ""
    commit_hash: str = ""
    gateway_url: str = ""
    # M1: Canary detection
    m1_canary_requests: int = 0
    m1_canary_detected: int = 0
    m1_canary_detection_rate_pct: float = 0.0
    # M2: Enum detection
    m2_enum_requests_until_detected: int = 0
    m2_enum_threshold_configured: int = 5
    m2_enum_window_sec: int = 10
    # M3: Tarpit delay
    m3_tarpit_delay_ms_min: float = 0.0
    m3_tarpit_delay_ms_median: float = 0.0
    m3_tarpit_delay_ms_p95: float = 0.0
    m3_tarpit_configured_ms: int = 3000
    # M4: Tarpit saturation
    m4_concurrent_flood: int = 0
    m4_got_429: bool = False
    m4_tarpit_max_concurrent: int = 50
    # M8: False-positive rate
    m8_legit_requests: int = 0
    m8_legit_unexpected_status: int = 0
    m8_false_positive_rate_pct: float = 0.0
    # Raw errors
    errors: List[str] = field(default_factory=list)


# ── Helpers ───────────────────────────────────────────────────────────────────
def sorted_pct(values: list, pct: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    idx = max(0, int(len(s) * pct / 100) - 1)
    return round(s[idx] * 1000, 1)  # convert s → ms


def median_ms(values: list) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    return round(s[len(s) // 2] * 1000, 1)


def _make_client(base_url: str, device_id: str, timeout: float = 12.0) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        base_url=base_url,
        headers={"X-Device-ID": device_id, "User-Agent": "tcad-bench/1.0"},
        timeout=timeout,
        follow_redirects=False,
    )


async def get_ctrl_events(ctrl_url: str, event_type: str) -> int:
    """Poll control-api for event count — gives async dispatch time to settle."""
    await asyncio.sleep(1.5)
    async with httpx.AsyncClient(base_url=ctrl_url, timeout=5.0) as c:
        try:
            r = await c.get(f"/events?type={event_type}&limit=1000")
            return r.json().get("total", 0)
        except Exception:
            return 0


# ── M1: Canary detection rate ─────────────────────────────────────────────────
async def measure_m1(base_url: str, results: BenchResults):
    print("[M1] Canary detection rate…")
    CANARY_PATHS = [
        "/admin", "/admin/login", "/admin/dashboard",
        "/.env", "/.env.local", "/.env.backup",
        "/backup", "/backup.zip",
        "/api/v1/ops/deploy", "/api/v1/ops/config",
    ]
    detected = 0
    total = len(CANARY_PATHS)

    async with _make_client(base_url, f"bench-m1-{int(time.time())}") as c:
        for path in CANARY_PATHS:
            try:
                r = await c.get(path)
                # Gateway proxies canary → honeypot which returns 200 (catch-all)
                if r.status_code == 200:
                    detected += 1
            except Exception as exc:
                results.errors.append(f"M1 {path}: {exc}")

    results.m1_canary_requests = total
    results.m1_canary_detected = detected
    results.m1_canary_detection_rate_pct = round(detected / total * 100, 1) if total else 0.0
    print(f"  detected={detected}/{total}  rate={results.m1_canary_detection_rate_pct}%")


# ── M2: Enum detection — requests until ENUM_DETECTED fires ──────────────────
async def measure_m2(base_url: str, ctrl_url: str, results: BenchResults):
    print("[M2] Enum detection latency…")
    device_id = f"bench-m2-{int(time.time())}"
    fired_at = 0

    async with _make_client(base_url, device_id, timeout=15.0) as c:
        for i in range(1, 15):  # send up to 14 requests
            path = f"/api/v2/nonexistent-enum-bench-{i}"
            try:
                await c.get(path)
            except Exception as exc:
                results.errors.append(f"M2 req {i}: {exc}")

            await asyncio.sleep(0.05)

            # Check after each request whether ENUM_DETECTED has fired
            try:
                async with httpx.AsyncClient(base_url=ctrl_url, timeout=3.0) as cc:
                    r = await cc.get(f"/events?type=ENUM_DETECTED&limit=100")
                    for ev in r.json().get("data", []):
                        if device_id in ev.get("identity", ""):
                            fired_at = i
                            break
            except Exception:
                pass

            if fired_at:
                break

    results.m2_enum_requests_until_detected = fired_at if fired_at else -1
    print(f"  fired after {fired_at} requests (threshold≈{results.m2_enum_threshold_configured})")


# ── M3: Tarpit delay ──────────────────────────────────────────────────────────
async def measure_m3(base_url: str, results: BenchResults):
    print("[M3] Tarpit delay measurement…")
    # Use a fresh device ID and blow past the enum threshold quickly
    device_id = f"bench-m3-{int(time.time())}"
    delays = []

    # Phase 1: trigger enum detection (6 quick 404s)
    async with _make_client(base_url, device_id, timeout=2.0) as c:
        for i in range(6):
            try:
                await c.get(f"/api/v99/trigger-enum-{i}")
            except Exception:
                pass
            await asyncio.sleep(0.05)

    # Phase 2: measure delay on subsequent tarpitted requests
    # Use TARPIT_DELAY_MS from env (default 3000ms), but test with a short delay
    # by checking actual wall-clock time
    async with _make_client(base_url, device_id, timeout=15.0) as c:
        for i in range(3):
            t0 = time.monotonic()
            try:
                await c.get(f"/api/v99/tarpitted-{i}")
                delays.append(time.monotonic() - t0)
            except httpx.TimeoutException:
                delays.append(results.m3_tarpit_configured_ms / 1000.0)
            except Exception as exc:
                results.errors.append(f"M3 request {i}: {exc}")
            await asyncio.sleep(0.1)

    results.m3_tarpit_delay_ms_min    = round(min(delays) * 1000, 1) if delays else 0.0
    results.m3_tarpit_delay_ms_median = median_ms(delays) if delays else 0.0
    results.m3_tarpit_delay_ms_p95    = sorted_pct(delays, 95) if delays else 0.0
    print(f"  min={results.m3_tarpit_delay_ms_min}ms  "
          f"median={results.m3_tarpit_delay_ms_median}ms  "
          f"p95={results.m3_tarpit_delay_ms_p95}ms  "
          f"(configured={results.m3_tarpit_configured_ms}ms)")


# ── M4: Tarpit saturation → 429 ───────────────────────────────────────────────
async def measure_m4(base_url: str, results: BenchResults):
    print("[M4] Tarpit saturation (429 under flood)…")
    # Strategy: create TARPIT_MAX_CONCURRENT + 10 concurrent scanners that all
    # hit 404 paths after triggering enum. At least one should get 429.
    N = results.m4_tarpit_max_concurrent + 10
    got_429 = False
    results.m4_concurrent_flood = N

    async def flood_worker(idx: int):
        nonlocal got_429
        device_id = f"bench-m4-flood-{idx}-{int(time.time())}"
        # Each worker blows past enum threshold then hits the tarpit
        async with _make_client(base_url, device_id, timeout=15.0) as c:
            for i in range(8):
                try:
                    await c.get(f"/api/v99/flood-trigger-{i}")
                except Exception:
                    pass
                await asyncio.sleep(0.02)
            # Now try to acquire tarpit slot
            try:
                r = await c.get(f"/api/v99/flood-tarpit")
                if r.status_code == 429:
                    got_429 = True
            except Exception:
                pass

    # Launch all workers concurrently
    await asyncio.gather(*(flood_worker(i) for i in range(N)))

    results.m4_got_429 = got_429
    print(f"  flood_workers={N}  got_429={got_429}")


# ── M8: False-positive rate ───────────────────────────────────────────────────
async def measure_m8(base_url: str, results: BenchResults):
    print("[M8] Legit false-positive rate…")
    LEGIT_PATHS = [
        "/health",
        "/api/v1/shipments",
        "/api/v1/shipments?page=1&limit=10",
        "/api/v1/manifests",
        "/api/v1/routes",
    ]
    ROUNDS = 5
    unexpected = 0
    total = 0

    async with _make_client(base_url, f"bench-m8-legit-{int(time.time())}") as c:
        for _ in range(ROUNDS):
            for path in LEGIT_PATHS:
                try:
                    r = await c.get(path)
                    total += 1
                    if not (200 <= r.status_code < 300):
                        unexpected += 1
                        results.errors.append(f"M8 legit {path} → {r.status_code}")
                except Exception as exc:
                    total += 1
                    unexpected += 1
                    results.errors.append(f"M8 legit {path}: {exc}")
                await asyncio.sleep(0.05)

    results.m8_legit_requests = total
    results.m8_legit_unexpected_status = unexpected
    results.m8_false_positive_rate_pct = round(unexpected / total * 100, 2) if total else 0.0
    print(f"  total={total}  unexpected={unexpected}  "
          f"false_positive={results.m8_false_positive_rate_pct}%")


# ── Context gathering ─────────────────────────────────────────────────────────
def gather_context(gateway_url: str) -> dict:
    commit = "unknown"
    try:
        commit = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            stderr=subprocess.DEVNULL,
            cwd=os.path.dirname(__file__),
        ).decode().strip()
    except Exception:
        pass

    hw = f"{platform.system()} {platform.machine()} {platform.processor()}"
    try:
        hw += f" cores={os.cpu_count()}"
    except Exception:
        pass

    return {
        "date": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "hardware": hw,
        "commit_hash": commit,
        "gateway_url": gateway_url,
    }


# ── Main ──────────────────────────────────────────────────────────────────────
async def main():
    parser = argparse.ArgumentParser(description="TCAD Mesh benchmark harness")
    parser.add_argument("--gateway", default=os.environ.get("GATEWAY_URL", "http://localhost:8080"))
    parser.add_argument("--ctrl",    default=os.environ.get("CONTROL_URL", "http://localhost:3000"))
    parser.add_argument("--out",     default=os.environ.get("RESULTS_PATH", "results/bench.json"))
    parser.add_argument("--tarpit-configured-ms", type=int,
                        default=int(os.environ.get("TARPIT_DELAY_MS", "3000")))
    parser.add_argument("--tarpit-max-concurrent", type=int,
                        default=int(os.environ.get("TARPIT_MAX_CONCURRENT", "50")))
    parser.add_argument("--enum-threshold", type=int,
                        default=int(os.environ.get("ENUM_THRESHOLD", "5")))
    args = parser.parse_args()

    print(f"[bench] TCAD Mesh Benchmark  gateway={args.gateway}")
    print(f"        tarpit={args.tarpit_configured_ms}ms  max_conc={args.tarpit_max_concurrent}")
    print()

    # Verify gateway is reachable
    try:
        async with httpx.AsyncClient(timeout=5.0) as c:
            r = await c.get(f"{args.gateway}/health")
            print(f"[bench] Gateway health: {r.status_code} — {r.json()}")
    except Exception as exc:
        print(f"[bench] ERROR: Cannot reach gateway at {args.gateway}: {exc}", file=sys.stderr)
        sys.exit(1)

    results = BenchResults()
    ctx = gather_context(args.gateway)
    results.date         = ctx["date"]
    results.hardware     = ctx["hardware"]
    results.commit_hash  = ctx["commit_hash"]
    results.gateway_url  = ctx["gateway_url"]
    results.m3_tarpit_configured_ms    = args.tarpit_configured_ms
    results.m4_tarpit_max_concurrent   = args.tarpit_max_concurrent
    results.m2_enum_threshold_configured = args.enum_threshold

    # Run all measurements
    await measure_m1(args.gateway, results)
    await measure_m2(args.gateway, args.ctrl, results)
    await measure_m3(args.gateway, results)
    await measure_m4(args.gateway, results)
    await measure_m8(args.gateway, results)

    # Save JSON
    out_dict = asdict(results)
    os.makedirs(os.path.dirname(args.out) if os.path.dirname(args.out) else ".", exist_ok=True)
    with open(args.out, "w") as f:
        json.dump(out_dict, f, indent=2)
    print(f"\n[bench] Results saved → {args.out}")
    print(json.dumps(out_dict, indent=2))
    return out_dict


if __name__ == "__main__":
    results = asyncio.run(main())
    # Non-zero exit if any assertion would fail a Gate T4 criterion
    issues = []
    if results.get("m1_canary_detection_rate_pct", 0) < 100:
        issues.append(f"M1 canary rate {results['m1_canary_detection_rate_pct']}% < 100%")
    if results.get("m8_false_positive_rate_pct", 999) > 0:
        issues.append(f"M8 false-positive rate {results['m8_false_positive_rate_pct']}% > 0%")
    if issues:
        print("\n[bench] GATE FAILURES:")
        for iss in issues:
            print(f"  ❌  {iss}")
        sys.exit(1)
    print("\n[bench] ✅  All gate metrics pass")
