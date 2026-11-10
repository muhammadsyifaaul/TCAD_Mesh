"""
attacker-sim/scenarios/legit.py
Legit scenario — simulates a well-behaved API client.

Gate T3 criterion: legit scenario generates ZERO alerts.

Rules:
  - Only hits registered API paths (no canary paths, no unknown paths).
  - Sends realistic pagination params.
  - Uses a stable device ID to accumulate a clean traffic history.
  - Never reuses any token or hits any path outside the published API.
"""
import asyncio
import time
from dataclasses import dataclass, field
from typing import List

import httpx

from client import make_client
from config import GATEWAY_URL, SIM_DELAY, SIM_TIMEOUT, LEGIT_PATHS


@dataclass
class LegitResult:
    scenario: str = "legit"
    started_at: str = ""
    finished_at: str = ""
    total_requests: int = 0
    success_count: int = 0        # 2xx responses
    unexpected_status: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)

    @property
    def alert_count(self) -> int:
        """Approximation: any non-2xx from a known-good path hints at an alert."""
        return len(self.unexpected_status)

    def as_dict(self) -> dict:
        return {
            "scenario": self.scenario,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "total_requests": self.total_requests,
            "success_count": self.success_count,
            "alert_count": self.alert_count,
            "unexpected_status": self.unexpected_status,
            "errors": self.errors,
        }


async def run(device_id: str = "legit-client-01", rounds: int = 3) -> LegitResult:
    """
    Execute the legit scenario.
    Sends `rounds` passes over all legit API paths.
    """
    result = LegitResult()
    result.started_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    async with make_client(GATEWAY_URL, device_id, timeout=SIM_TIMEOUT) as client:
        for _ in range(rounds):
            for path in LEGIT_PATHS:
                try:
                    resp = await client.get(path)
                    result.total_requests += 1
                    if 200 <= resp.status_code < 300:
                        result.success_count += 1
                    else:
                        result.unexpected_status.append(
                            f"{path} → {resp.status_code}"
                        )
                except Exception as exc:
                    result.errors.append(f"{path}: {exc}")

                await asyncio.sleep(SIM_DELAY)

    result.finished_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    return result
