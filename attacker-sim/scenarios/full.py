"""
attacker-sim/scenarios/full.py
Full demo scenario — the one-click judge demo sequence.

Sequence (all identities are unique per run via run_id suffix):
  0. POST /reset via control-api so every run starts from a clean slate.
  1. legit_pre  — 2 rounds of clean traffic from "demo-legit-pre-<rid>"  (0 alerts expected)
  2. scan       — canary probing + enumeration from "demo-attacker-<rid>" and
                  "demo-attacker-<rid>-enum":
                    → CANARY_HIT, QUARANTINED, ENUM_DETECTED, TARPIT_ACTIVE
  3. honeypot   — the quarantined attacker hits the shipments endpoint and
                  receives honeypot data with a honeytoken embedded:
                    → HONEYTOKEN_ISSUED, registered in control-api
  4. reuse      — a *second* identity "demo-reuser-<rid>" uses the captured
                  honeytoken in a request URI, triggering detection:
                    → HONEYTOKEN_REUSED (detail.original_session = attacker session)
  5. release    — operator releases the original attacker quarantine via
                  POST /quarantine/{identity}/release (optional, best-effort)
  6. legit_post — 2 rounds of clean traffic from "demo-legit-post-<rid>"
                  confirms legitimate clients still work after the attack

The dashboard's "🎬 Full Demo" button triggers this via POST /sim/run {"scenario":"full"}.
"""
import asyncio
import os
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

import httpx

from allowlist import validate_target
from client import make_client
from config import GATEWAY_URL, CONTROL_URL, INTERNAL_KEY, SIM_TIMEOUT, SIM_DELAY
from scenarios.legit import run as run_legit, LegitResult
from scenarios.scan  import run as run_scan,  ScanResult


def _ctrl_url() -> str:
    return os.environ.get("CONTROL_URL", CONTROL_URL)

def _ikey() -> str:
    return os.environ.get("INTERNAL_KEY", INTERNAL_KEY)


@dataclass
class FullResult:
    scenario:    str = "full"
    run_id:      str = ""
    started_at:  str = ""
    finished_at: str = ""
    phases:      Dict[str, Any] = field(default_factory=dict)
    honeytoken:  Optional[str] = None          # token captured from honeypot phase
    reuse_fired: bool = False                   # True if HONEYTOKEN_REUSED confirmed

    def as_dict(self) -> dict:
        return {
            "scenario":    self.scenario,
            "run_id":      self.run_id,
            "started_at":  self.started_at,
            "finished_at": self.finished_at,
            "phases":      self.phases,
            "honeytoken":  self.honeytoken,
            "reuse_fired": self.reuse_fired,
        }


async def _reset() -> bool:
    """POST /reset to control-api — clears all events/quarantines/honeytokens."""
    try:
        validate_target(_ctrl_url())
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.post(
                f"{_ctrl_url()}/reset",
                headers={"X-Internal-Key": _ikey()},
            )
            return r.status_code == 200
    except Exception as exc:
        print(f"[full] WARNING: reset failed: {exc}")
        return False


async def _get_honeytoken_for_identity(identity: str) -> Optional[str]:
    """
    Poll GET /honeytokens and find the token that belongs to `identity`.
    Retries for up to 4 s to allow the honeypot's async register call to land.
    Returns the token string or None.
    """
    try:
        validate_target(_ctrl_url())
        for _ in range(8):
            async with httpx.AsyncClient(timeout=5.0) as client:
                r = await client.get(f"{_ctrl_url()}/honeytokens")
            if r.status_code == 200:
                tokens = r.json().get("tokens", [])
                for t in tokens:
                    if isinstance(t, dict) and t.get("identity") == identity:
                        return t["token"]
            await asyncio.sleep(0.5)
    except Exception as exc:
        print(f"[full] WARNING: honeytoken poll failed: {exc}")
    return None


async def _check_reuse_event(token: str) -> bool:
    """Return True if any HONEYTOKEN_REUSED event in /events mentions this token."""
    try:
        validate_target(_ctrl_url())
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.get(
                f"{_ctrl_url()}/events",
                params={"type": "HONEYTOKEN_REUSED", "limit": 50},
            )
        if r.status_code != 200:
            return False
        events = r.json().get("data", [])
        for ev in events:
            detail = ev.get("detail") or {}
            if detail.get("token") == token or ev.get("path", "").find(token) != -1:
                return True
    except Exception:
        pass
    return False


async def run() -> FullResult:
    result = FullResult()
    result.run_id     = uuid.uuid4().hex[:8]        # e.g. "a3f5b7c2"
    result.started_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    rid = result.run_id

    # ── Phase 0: Reset — fresh start, no identity collisions ─────────────────
    print(f"[full/{rid}] Phase 0/6 — reset demo data...")
    ok = await _reset()
    result.phases["reset"] = {"ok": ok}
    print(f"[full/{rid}]   reset: {'OK' if ok else 'FAILED (continuing anyway)'}")

    # Give the gateway's quarantine poller a moment to pick up the new epoch
    await asyncio.sleep(1.5)

    # ── Phase 1: Legit baseline ───────────────────────────────────────────────
    print(f"[full/{rid}] Phase 1/6 — legit baseline (device demo-legit-pre-{rid})...")
    legit1: LegitResult = await run_legit(device_id=f"demo-legit-pre-{rid}", rounds=2)
    result.phases["legit_pre"] = legit1.as_dict()
    print(f"[full/{rid}]   legit pre: {legit1.success_count}/{legit1.total_requests} ok, "
          f"alerts={legit1.alert_count}")

    # ── Phase 2: Scan — canary + enumeration ─────────────────────────────────
    attacker_id = f"demo-attacker-{rid}"
    print(f"[full/{rid}] Phase 2/6 — attacker scan (device {attacker_id})...")
    scan: ScanResult = await run_scan(device_id=attacker_id)
    result.phases["scan"] = scan.as_dict()
    print(f"[full/{rid}]   scan: {scan.total_requests} reqs, "
          f"canary_hits={scan.canary_hits}, enum_triggers={scan.enum_trigger_requests}")

    # Let async events settle + quarantine poller cycle
    await asyncio.sleep(2.0)

    # ── Phase 3: Honeypot data extraction ────────────────────────────────────
    # The attacker (now quarantined) hits /api/v1/shipments → receives honeypot
    # data. Each response embeds a honeytoken; we capture it for phase 4.
    # NOTE: scan already hits the honeypot via canary+catch-all, but those use
    # a different session per request. We do one explicit call here with a
    # stable session header so the token is reliably attributed.
    print(f"[full/{rid}] Phase 3/6 — honeypot data capture (device {attacker_id})...")
    honeypot_session = f"sess-attacker-{rid}"
    captured_token: Optional[str] = None
    try:
        async with make_client(
            GATEWAY_URL, attacker_id,
            timeout=SIM_TIMEOUT,
            extra_headers={"X-Session-ID": honeypot_session},
        ) as client:
            resp = await client.get("/api/v1/shipments")
            if resp.status_code == 200:
                body = resp.json()
                data = body.get("data", [])
                if data:
                    captured_token = data[0].get("id")
    except Exception as exc:
        print(f"[full/{rid}]   WARNING: honeypot fetch failed: {exc}")

    result.phases["honeypot_capture"] = {
        "identity":       attacker_id,
        "session_id":     honeypot_session,
        "captured_token": captured_token,
    }
    print(f"[full/{rid}]   captured token: {captured_token}")

    # Wait for honeypot's async register_honeytoken call to land in control-api,
    # then confirm via GET /honeytokens
    await asyncio.sleep(2.0)
    if captured_token is None:
        # Try to find any token registered to this identity
        captured_token = await _get_honeytoken_for_identity(attacker_id)
        result.phases["honeypot_capture"]["captured_token"] = captured_token
        print(f"[full/{rid}]   token from registry: {captured_token}")

    result.honeytoken = captured_token

    # ── Phase 4: Honeytoken reuse by a second identity ────────────────────────
    # A *different* identity (simulating the attacker pivoting to a new device
    # or handing the token to a partner) reuses the captured token.
    # Expected event: HONEYTOKEN_REUSED with detail.original_session = honeypot_session
    reuser_id = f"demo-reuser-{rid}"
    print(f"[full/{rid}] Phase 4/6 — honeytoken reuse (device {reuser_id})...")
    reuse_fired = False
    if captured_token:
        try:
            # Wait for gateway to poll honeytoken registry (up to 2 polls = 2 × 500 ms + buffer)
            await asyncio.sleep(1.5)
            async with make_client(GATEWAY_URL, reuser_id, timeout=SIM_TIMEOUT) as client:
                # Embed token in query string — gateway scans URI for registered tokens
                resp = await client.get(f"/api/v1/shipments?doc={captured_token}")
                reuse_status = resp.status_code
            print(f"[full/{rid}]   reuser request status: {reuse_status}")
            # Allow async HONEYTOKEN_REUSED event to dispatch
            await asyncio.sleep(2.0)
            reuse_fired = await _check_reuse_event(captured_token)
        except Exception as exc:
            print(f"[full/{rid}]   WARNING: reuse request failed: {exc}")
    else:
        print(f"[full/{rid}]   SKIP: no token captured, cannot test reuse")

    result.reuse_fired = reuse_fired
    result.phases["honeytoken_reuse"] = {
        "reuser_id":     reuser_id,
        "token":         captured_token,
        "reuse_fired":   reuse_fired,
    }
    print(f"[full/{rid}]   HONEYTOKEN_REUSED fired: {reuse_fired}")

    # ── Phase 5: Operator quarantine release (best-effort) ───────────────────
    print(f"[full/{rid}] Phase 5/6 — release attacker quarantine (best-effort)...")
    released = False
    try:
        validate_target(_ctrl_url())
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.post(
                f"{_ctrl_url()}/quarantine/{attacker_id}/release",
                headers={"X-Internal-Key": _ikey()},
            )
            released = r.status_code == 200
    except Exception:
        pass
    result.phases["release"] = {"identity": attacker_id, "released": released}
    print(f"[full/{rid}]   release: {'OK' if released else 'skipped/failed'}")

    await asyncio.sleep(1.0)

    # ── Phase 6: Post-attack legit check ─────────────────────────────────────
    print(f"[full/{rid}] Phase 6/6 — legit post-attack (device demo-legit-post-{rid})...")
    legit2: LegitResult = await run_legit(device_id=f"demo-legit-post-{rid}", rounds=2)
    result.phases["legit_post"] = legit2.as_dict()
    print(f"[full/{rid}]   legit post: {legit2.success_count}/{legit2.total_requests} ok, "
          f"alerts={legit2.alert_count}")

    result.finished_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    return result
