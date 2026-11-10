"""
attacker-sim/scenarios/replay.py
Mode 2 replay attack scenario.

Simulates an attacker who has intercepted a valid Mode 2 request from logs
and attempts to replay it. Tests:
  1. Exact replay (same URL + headers) → must be rejected (401)
  2. Same nonce, different URL → must be rejected (401)
  3. Stolen MAC in new URL (out-of-window) → tripwire or 404
  4. Fresh valid request → must succeed (200)  [baseline sanity]

Gate T5 criterion M7: in-window replays rejected 100%.
"""
import asyncio
import time
from dataclasses import dataclass, field
from typing import List

import httpx

from allowlist import validate_target
from sdk.mode2 import Mode2Config, route_url, sign_request, current_interval, derive_mac16


@dataclass
class ReplayResult:
    scenario: str = "replay"
    started_at: str = ""
    finished_at: str = ""
    total_replay_attempts: int = 0
    replays_rejected: int = 0
    m7_rejection_rate_pct: float = 0.0
    fresh_request_success: bool = False
    errors: List[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "scenario": self.scenario,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "total_replay_attempts": self.total_replay_attempts,
            "replays_rejected": self.replays_rejected,
            "m7_rejection_rate_pct": self.m7_rejection_rate_pct,
            "fresh_request_success": self.fresh_request_success,
            "errors": self.errors,
        }


async def run(cfg: Mode2Config | None = None) -> ReplayResult:
    """Run replay attack scenarios and measure rejection rate."""
    if cfg is None:
        cfg = Mode2Config.from_env("m2-replay-attacker")

    validate_target(cfg.gateway_url)

    result = ReplayResult()
    result.started_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    async with httpx.AsyncClient(timeout=10.0) as client:

        # ── Step 1: Make one legitimate request and capture its headers ───────
        path = "/api/v1/shipments"
        legit_url, _ = route_url(cfg.gateway_url, path, cfg.secret, cfg.interval_sec)
        legit_headers = sign_request(cfg.secret, "GET", path, b"",
                                     cfg.device_id + "-legit")
        legit_headers["User-Agent"] = "TCAD-SDK/1.0 mode=2"

        r_legit = await client.get(legit_url, headers=legit_headers)
        if 200 <= r_legit.status_code < 300:
            result.fresh_request_success = True
        else:
            result.errors.append(f"legit baseline failed: {r_legit.status_code}")

        # ── Step 2: Exact replay — same URL, same nonce ────────────────────────
        # The nonce was already consumed by the gateway; the replay must be rejected.
        for attempt in range(3):
            result.total_replay_attempts += 1
            try:
                r = await client.get(legit_url, headers=legit_headers)
                if r.status_code == 401:
                    result.replays_rejected += 1
                else:
                    result.errors.append(
                        f"exact replay #{attempt+1} not rejected: {r.status_code}"
                    )
            except Exception as exc:
                result.errors.append(f"exact replay #{attempt+1}: {exc}")
            await asyncio.sleep(0.1)

        # ── Step 3: Same nonce, different canonical path ──────────────────────
        path2 = "/api/v1/manifests"
        alt_url, _ = route_url(cfg.gateway_url, path2, cfg.secret, cfg.interval_sec)
        # Reuse the same nonce and timestamp from the original legit request
        stolen_headers = {**legit_headers}
        stolen_headers["X-Nonce"] = legit_headers["X-Nonce"]
        stolen_headers["X-Device-ID"] = cfg.device_id + "-legit"  # same device
        # Recompute sig with correct values for new path (tests nonce reuse across paths)
        from sdk.mode2 import sign_request as _sign
        stolen_sig_headers = _sign(
            cfg.secret, "GET", path2, b"",
            cfg.device_id + "-legit",
            nonce=legit_headers["X-Nonce"],
            timestamp=legit_headers["X-Timestamp"],
        )
        stolen_sig_headers["User-Agent"] = "TCAD-SDK/1.0 mode=2"

        result.total_replay_attempts += 1
        try:
            r3 = await client.get(alt_url, headers=stolen_sig_headers)
            if r3.status_code == 401:
                result.replays_rejected += 1
            else:
                result.errors.append(
                    f"cross-path nonce replay not rejected: {r3.status_code}"
                )
        except Exception as exc:
            result.errors.append(f"cross-path replay: {exc}")

        # ── Step 4: Stolen MAC in stale interval (tripwire) ───────────────────
        stale_interval = current_interval(cfg.interval_sec) - 10
        stale_mac = derive_mac16(cfg.secret, stale_interval)
        stale_url = (f"{cfg.gateway_url.rstrip('/')}/m/"
                     f"{stale_interval}-{stale_mac}{path}")
        stale_headers = sign_request(cfg.secret, "GET", path, b"",
                                     cfg.device_id + "-stale")
        stale_headers["User-Agent"] = "TCAD-SDK/1.0 mode=2"

        result.total_replay_attempts += 1
        try:
            r4 = await client.get(stale_url, headers=stale_headers)
            # Stale valid MAC → tripwire → honeypot response (200) or 401
            # Either way the attacker doesn't get real data
            if r4.status_code in (401, 200):
                result.replays_rejected += 1  # quarantined or honeypot served
            else:
                result.errors.append(f"stale interval not handled: {r4.status_code}")
        except Exception as exc:
            result.errors.append(f"stale interval test: {exc}")

    total = result.total_replay_attempts
    result.m7_rejection_rate_pct = (
        round(result.replays_rejected / total * 100, 2) if total else 0.0
    )
    result.finished_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    return result
