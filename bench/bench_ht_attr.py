"""
bench/bench_ht_attr.py
Honeytoken attribution: per-token session_id verification.

For each delay (0, 1, 2, 3 s) with ≥30 tokens per batch (fresh DB each):
1. Quarantine attacker via /admin  
2. Get honeypot shipments — capture token + session_id
3. Wait `delay` seconds  
4. Reuse token in URI from a DIFFERENT identity
5. Wait 3s for event propagation  
6. Check: is there a HONEYTOKEN_REUSED event whose
   detail.original_session == session_id from step 2?
   (This is the correctness check, not just an event count delta)
7. Report exact hits/total per delay

Also checks the 19/20 anomaly from the previous run at 3s delay.
"""
import asyncio
import json
import os
import platform
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass, field, asdict
from typing import List, Optional

import httpx

REAL_IDS = {
    "DOC-1a2b3c4d5e6f","DOC-2b3c4d5e6f7a",
    "DOC-3c4d5e6f7a8b","DOC-4d5e6f7a8b9c","DOC-5e6f7a8b9c0d",
}


@dataclass
class TokenResult:
    token: str
    session_id: str        # session that RECEIVED the token
    reuse_device_id: str   # different identity that reused the token
    delay_s: float
    detected: bool         # True if HONEYTOKEN_REUSED event has original_session==session_id
    event_found: bool      # True if ANY HONEYTOKEN_REUSED event mentions this token
    failure_reason: str = ""


@dataclass
class HTAttrResults:
    date: str = ""
    hardware: str = ""
    commit_hash: str = ""
    delays: List[dict] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)


async def reset_db(ctrl: str, ikey: str) -> None:
    async with httpx.AsyncClient(base_url=ctrl, timeout=5.0) as c:
        await c.post("/reset", headers={"X-Internal-Key": ikey})
        await asyncio.sleep(0.5)


async def run_delay_batch(gateway: str, ctrl: str, delay_s: float, n: int,
                          ikey: str) -> dict:
    """Run one delay batch. Returns summary dict."""
    results: List[TokenResult] = []

    for i in range(n):
        did_a = f"ht-attr-A-d{int(delay_s)}-{i}-{uuid.uuid4().hex[:6]}"
        sid = f"sess-{uuid.uuid4().hex[:8]}"
        did_b = f"ht-attr-B-d{int(delay_s)}-{i}-{uuid.uuid4().hex[:6]}"

        tr = TokenResult(token="", session_id=sid, reuse_device_id=did_b,
                         delay_s=delay_s, detected=False, event_found=False)

        # Step 1: Quarantine via canary
        async with httpx.AsyncClient(base_url=gateway, timeout=10.0,
                                      headers={"X-Device-ID": did_a,
                                               "X-Session-ID": sid}) as c:
            await c.get("/admin")
            await asyncio.sleep(0.15)

            # Step 2: Get honeypot response — capture token
            r = await c.get("/api/v1/shipments")
            try:
                data = r.json().get("data", [])
                token = data[0]["id"] if data else ""
            except Exception:
                token = ""

        if not token or token in REAL_IDS:
            tr.failure_reason = "could not extract honeytoken from honeypot response"
            results.append(tr)
            continue

        tr.token = token

        # Step 3: Wait the specified delay
        await asyncio.sleep(delay_s)

        # Step 4: Reuse token from a DIFFERENT identity
        async with httpx.AsyncClient(base_url=gateway, timeout=10.0,
                                      headers={"X-Device-ID": did_b}) as c:
            await c.get(f"/api/v1/shipments?doc={token}")

        results.append(tr)

    # Step 5: Wait for events to propagate (3s)
    await asyncio.sleep(3)

    # Step 6: Check HONEYTOKEN_REUSED events
    # Fetch all events and look for ones matching our tokens
    async with httpx.AsyncClient(base_url=ctrl, timeout=10.0) as c:
        r = await c.get("/events?type=HONEYTOKEN_REUSED&limit=1000")
        reuse_events = r.json().get("data", [])

    # Build lookup: token → list of events
    events_by_token: dict = {}
    for ev in reuse_events:
        detail = ev.get("detail", {}) or {}
        t = detail.get("token", "")
        if t:
            events_by_token.setdefault(t, []).append(ev)

    correct = 0
    event_found_count = 0
    for tr in results:
        if not tr.token:
            continue
        evts = events_by_token.get(tr.token, [])
        if evts:
            tr.event_found = True
            event_found_count += 1
            # Check session_id attribution: detail.original_session == tr.session_id
            for ev in evts:
                detail = ev.get("detail", {}) or {}
                if detail.get("original_session") == tr.session_id:
                    tr.detected = True
                    correct += 1
                    break

    total = sum(1 for r in results if r.token)
    return {
        "delay_s": delay_s,
        "n_total": total,
        "n_event_found": event_found_count,
        "n_session_match": correct,
        "detection_rate_pct": round(correct / max(1, total) * 100, 1),
        "per_token": [
            {
                "token": r.token,
                "session_id": r.session_id,
                "detected": r.detected,
                "event_found": r.event_found,
                "failure": r.failure_reason,
            }
            for r in results
        ],
    }


async def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--gateway", default=os.environ.get("GATEWAY_URL", "http://gateway:8080"))
    parser.add_argument("--ctrl",   default=os.environ.get("CONTROL_URL", "http://control-api:8003"))
    parser.add_argument("--ikey",   default=os.environ.get("INTERNAL_KEY", "change-me"))
    parser.add_argument("--n",      type=int, default=30)
    parser.add_argument("--out",    default="results/bench_ht_attr.json")
    args = parser.parse_args()

    print(f"[ht_attr] Per-token honeytoken attribution  n={args.n} per delay")
    print(f"  gateway={args.gateway}  ctrl={args.ctrl}")
    print()

    results = HTAttrResults()
    results.date = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    results.hardware = f"{platform.system()} {platform.machine()} cores={os.cpu_count()}"
    try:
        results.commit_hash = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"], stderr=subprocess.DEVNULL
        ).decode().strip()
    except Exception:
        results.commit_hash = "pre-init"

    for delay in [0, 1, 2, 3]:
        print(f"=== Delay: {delay}s  (fresh DB before batch) ===")
        await reset_db(args.ctrl, args.ikey)
        print(f"  DB reset. Running {args.n} tokens sequentially…")

        batch = await run_delay_batch(args.gateway, args.ctrl, float(delay),
                                       args.n, args.ikey)

        print(f"  n_total={batch['n_total']}")
        print(f"  event_found={batch['n_event_found']}/{batch['n_total']}  "
              f"(any HONEYTOKEN_REUSED event exists for token)")
        print(f"  session_match={batch['n_session_match']}/{batch['n_total']}  "
              f"(event.detail.original_session == issuing session_id)")
        print(f"  detection_rate={batch['detection_rate_pct']}%  "
              f"(session-verified attribution)")
        print()

        # Show misses
        misses = [t for t in batch["per_token"] if not t["detected"] and not t["failure"]]
        if misses:
            print(f"  MISSES ({len(misses)}):")
            for m in misses[:5]:
                print(f"    token={m['token']}  event_found={m['event_found']}")

        results.delays.append(batch)

    # Save (omit per_token to keep file manageable)
    out_dict = asdict(results)
    for d in out_dict["delays"]:
        d.pop("per_token", None)

    os.makedirs(os.path.dirname(args.out) if os.path.dirname(args.out) else ".", exist_ok=True)
    with open(args.out, "w") as f:
        json.dump(out_dict, f, indent=2)
    print(f"[ht_attr] Results saved → {args.out}")


if __name__ == "__main__":
    asyncio.run(main())
