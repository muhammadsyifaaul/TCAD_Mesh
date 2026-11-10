"""
attacker-sim/scenarios/scan.py
Scan scenario — simulates a reconnaissance attacker probing for:
  1. Canary paths  (3 wordlists: admin, secrets, ops)
  2. API enumeration  (random 404s to trigger ENUM_DETECTED + tarpit)

Expected events fired:
  CANARY_HIT, QUARANTINED, ENUM_DETECTED, TARPIT_ACTIVE or TARPIT_SATURATED
"""
import asyncio
import time
from dataclasses import dataclass, field
from typing import List

import httpx

from client import make_client
from config import (
    GATEWAY_URL, SIM_DELAY, SIM_TIMEOUT,
    CANARY_WORDLIST, SECRETS_WORDLIST, OPS_WORDLIST, ENUM_WORDLIST,
)


@dataclass
class ScanResult:
    scenario: str = "scan"
    started_at: str = ""
    finished_at: str = ""
    total_requests: int = 0
    canary_hits: int = 0          # requests that hit a canary path (got 200 from honeypot)
    enum_trigger_requests: int = 0
    tarpit_delays: List[float] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    paths_probed: List[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "scenario": self.scenario,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "total_requests": self.total_requests,
            "canary_hits": self.canary_hits,
            "enum_trigger_requests": self.enum_trigger_requests,
            "avg_tarpit_delay_ms": (
                round(sum(self.tarpit_delays) / len(self.tarpit_delays) * 1000, 1)
                if self.tarpit_delays else 0
            ),
            "errors": self.errors,
            "paths_probed": self.paths_probed,
        }


async def run(device_id: str = "attacker-scan-01") -> ScanResult:
    """
    Execute the full scan scenario.
    device_id identifies this simulated attacker to the gateway.
    """
    result = ScanResult()
    result.started_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    async with make_client(GATEWAY_URL, device_id, timeout=SIM_TIMEOUT) as client:

        # ── Phase 1: Canary probing — three wordlists ─────────────────────────
        for wordlist_name, wordlist in [
            ("canary",  CANARY_WORDLIST),
            ("secrets", SECRETS_WORDLIST),
            ("ops",     OPS_WORDLIST),
        ]:
            for path in wordlist:
                try:
                    t0 = time.monotonic()
                    resp = await client.get(path)
                    elapsed = time.monotonic() - t0
                    result.total_requests += 1
                    result.paths_probed.append(path)

                    # Gateway proxies canary hits to honeypot → 200
                    if resp.status_code == 200:
                        result.canary_hits += 1

                    # If tarpit delay observable (>= 1s), record it
                    if elapsed >= 1.0:
                        result.tarpit_delays.append(elapsed)

                except httpx.TimeoutException:
                    result.total_requests += 1
                    result.tarpit_delays.append(SIM_TIMEOUT)
                    result.paths_probed.append(path)
                except Exception as exc:
                    result.errors.append(f"{path}: {exc}")

                await asyncio.sleep(SIM_DELAY)

        # ── Phase 2: API enumeration — trigger ENUM_DETECTED ─────────────────
        # Use a fresh device ID so enumeration isn't confused with canary hits
        enum_device = device_id + "-enum"

    async with make_client(GATEWAY_URL, enum_device, timeout=SIM_TIMEOUT) as client:
        for path in ENUM_WORDLIST:
            try:
                t0 = time.monotonic()
                resp = await client.get(path)
                elapsed = time.monotonic() - t0
                result.total_requests += 1
                result.paths_probed.append(path)
                result.enum_trigger_requests += 1

                if resp.status_code == 429:
                    pass  # Tarpit saturated — expected after threshold
                elif elapsed >= 1.0:
                    result.tarpit_delays.append(elapsed)

            except httpx.TimeoutException:
                result.total_requests += 1
                result.tarpit_delays.append(SIM_TIMEOUT)
            except Exception as exc:
                result.errors.append(f"{path}: {exc}")

            await asyncio.sleep(SIM_DELAY)

    result.finished_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    return result
