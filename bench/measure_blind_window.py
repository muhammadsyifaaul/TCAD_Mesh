"""
bench/measure_blind_window.py

Measures the honeytoken blind window attribution rate at different reuse delays
with HONEYTOKEN_POLL_MS=100 (the new default).

For each delay (0, 0.25, 0.5, 1.0 seconds):
  1. POST /reset (fresh DB)
  2. For each of 30 tokens:
     a. Quarantine identity-A via canary hit on /admin
     b. Get honeypot shipments (captures token from response)
     c. Wait for gateway to poll honeytoken list (poll_ms + buffer)
     d. Wait the reuse delay
     e. Identity-B reuses token in ?doc= query
     f. Wait for async event dispatch
     g. Check if HONEYTOKEN_REUSED event exists with correct original_session
  3. Report: matched/total per delay

Also measures:
  - Idle CPU/latency (no load)
  - 50 rps gateway latency (k6 or simple loop)

Usage (inside control-api container which has httpx):
  python3 /workspace/bench/measure_blind_window.py
"""
import httpx
import time
import json
import sys
import os

GATEWAY = os.environ.get("GATEWAY_URL", "http://gateway:8080")
CONTROL = os.environ.get("CONTROL_URL", "http://localhost:8003")
IKEY = os.environ.get("INTERNAL_KEY", "change-me-to-a-random-32-char-string")
BATCH_SIZE = 30
DELAYS = [0.0, 0.25, 0.5, 1.0]
POLL_MS = 100  # current setting


def reset_db(client):
    """POST /reset to clear all events, quarantine, honeytokens."""
    try:
        r = client.post(f"{CONTROL}/reset", headers={"X-Internal-Key": IKEY})
        return r.status_code == 200
    except Exception:
        return False


def check_reuse_event(client, token, reuser_id, timeout_s=5):
    """Poll for HONEYTOKEN_REUSED event matching this token and reuser."""
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            r = client.get(
                f"{CONTROL}/events",
                params={"type": "HONEYTOKEN_REUSED", "limit": 200},
            )
            if r.status_code == 200:
                for ev in r.json().get("data", []):
                    detail = ev.get("detail") or {}
                    ev_token = detail.get("token", "")
                    orig_session = detail.get("original_session", "")
                    ev_identity = ev.get("identity", "")
                    # Match: token in path or detail, and identity is our reuser
                    path = ev.get("path", "")
                    if (token in path or ev_token == token) and ev_identity == reuser_id:
                        # Check correct attribution: original_session present and != reuser
                        if orig_session and orig_session != reuser_id:
                            return True, "correct"
                        else:
                            return True, "wrong_attribution"
        except Exception:
            pass
        time.sleep(0.2)
    return False, "timeout"


def measure_batch(delay_s):
    """Run one batch of 30 tokens at the given reuse delay."""
    client = httpx.Client(timeout=10.0)
    reset_db(client)
    time.sleep(2)  # let gateway quarantine poller sync epoch

    matched = 0
    wrong_attr = 0
    missed = 0
    results = []

    for i in range(BATCH_SIZE):
        ts = int(time.time() * 1000)
        attacker_id = f"bw-att-{ts}-{i}"
        reuser_id = f"bw-reuse-{ts}-{i}"

        # Step 1: Quarantine via canary
        try:
            client.get(f"{GATEWAY}/admin", headers={"X-Device-ID": attacker_id})
        except Exception:
            pass
        time.sleep(0.3)

        # Step 2: Get honeypot data (captures token)
        try:
            r = client.get(
                f"{GATEWAY}/api/v1/shipments",
                headers={"X-Device-ID": attacker_id},
            )
            token = r.json()["data"][0]["id"]
        except Exception:
            missed += 1
            continue

        # Step 3: Wait for gateway to poll honeytoken list
        # poll_ms=100 → 1 poll cycle + buffer
        time.sleep(0.3)

        # Step 4: Wait the reuse delay
        if delay_s > 0:
            time.sleep(delay_s)

        # Step 5: Reuser reuses the token
        try:
            client.get(
                f"{GATEWAY}/api/v1/shipments",
                params={"doc": token},
                headers={"X-Device-ID": reuser_id},
            )
        except Exception:
            pass

        # Step 6: Wait for async event dispatch
        time.sleep(1.0)

        # Step 7: Check for HONEYTOKEN_REUSED event
        found, status = check_reuse_event(client, token, reuser_id, timeout_s=3)
        if found and status == "correct":
            matched += 1
        elif found and status == "wrong_attribution":
            wrong_attr += 1
        else:
            missed += 1

    client.close()
    return {
        "delay_s": delay_s,
        "total": BATCH_SIZE,
        "matched": matched,
        "wrong_attribution": wrong_attr,
        "missed": missed,
        "rate": f"{matched}/{BATCH_SIZE} ({matched*100//BATCH_SIZE}%)",
    }


def measure_idle_latency():
    """Measure gateway /health latency at idle."""
    client = httpx.Client(timeout=5.0)
    latencies = []
    for _ in range(20):
        t0 = time.monotonic()
        client.get(f"{GATEWAY}/health")
        latencies.append((time.monotonic() - t0) * 1000)
    client.close()
    latencies.sort()
    return {
        "p50": round(latencies[10], 1),
        "p95": round(latencies[18], 1),
        "p99": round(latencies[19], 1),
    }


def measure_50rps_latency():
    """Measure gateway latency under ~50 rps sustained load (10s)."""
    import concurrent.futures
    client = httpx.Client(timeout=5.0)
    latencies = []
    errors = 0

    def make_request():
        try:
            t0 = time.monotonic()
            r = client.get(
                f"{GATEWAY}/api/v1/shipments",
                headers={"X-Device-ID": f"load-test-{time.time()}"},
            )
            return (time.monotonic() - t0) * 1000
        except Exception:
            return None

    # 500 requests over 10s = 50 rps
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as pool:
        futures = []
        for _ in range(500):
            futures.append(pool.submit(make_request))
            time.sleep(0.02)  # 50 rps

        for f in concurrent.futures.as_completed(futures, timeout=15):
            result = f.result()
            if result is not None:
                latencies.append(result)
            else:
                errors += 1

    client.close()
    latencies.sort()
    if len(latencies) < 10:
        return {"error": "too few successful requests", "errors": errors}
    return {
        "total_requests": 500,
        "successful": len(latencies),
        "errors": errors,
        "p50": round(latencies[len(latencies)//2], 1),
        "p95": round(latencies[int(len(latencies)*0.95)], 1),
        "p99": round(latencies[int(len(latencies)*0.99)], 1),
    }


def main():
    print(f"=== Honeytoken Blind Window Measurement ===")
    print(f"HONEYTOKEN_POLL_MS = {POLL_MS}")
    print(f"Batch size = {BATCH_SIZE} tokens per delay")
    print(f"Delays = {DELAYS} seconds")
    print()

    # Idle latency
    print("Measuring idle /health latency...")
    idle = measure_idle_latency()
    print(f"  Idle: p50={idle['p50']}ms, p95={idle['p95']}ms, p99={idle['p99']}ms")
    print()

    # 50 rps latency
    print("Measuring 50 rps load latency (500 requests over 10s)...")
    load = measure_50rps_latency()
    print(f"  50rps: {load}")
    print()

    # Attribution per delay
    all_results = []
    for delay in DELAYS:
        print(f"Measuring attribution at {delay}s reuse delay ({BATCH_SIZE} tokens)...")
        result = measure_batch(delay)
        all_results.append(result)
        print(f"  Result: {result['rate']} (matched={result['matched']}, wrong_attr={result['wrong_attribution']}, missed={result['missed']})")
        print()

    # Summary
    print("\n=== Summary ===")
    print(f"HONEYTOKEN_POLL_MS = {POLL_MS}")
    print(f"Idle latency: p50={idle['p50']}ms, p95={idle['p95']}ms")
    print(f"50 rps latency: p50={load.get('p50','N/A')}ms, p95={load.get('p95','N/A')}ms, errors={load.get('errors','N/A')}")
    print()
    print("Attribution rates:")
    for r in all_results:
        print(f"  {r['delay_s']}s delay: {r['rate']}")

    # JSON output for parsing
    output = {
        "poll_ms": POLL_MS,
        "idle_latency": idle,
        "load_50rps": load,
        "attribution": all_results,
    }
    print(f"\n{json.dumps(output, indent=2)}")


if __name__ == "__main__":
    main()
