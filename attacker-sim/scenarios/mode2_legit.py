"""
attacker-sim/scenarios/mode2_legit.py
Mode 2 legit client scenario.

Sends properly signed requests with valid dynamic routes and anti-replay headers.
Tests clock drift tolerance: ±45s must succeed >99.9% of the time with GRACE=1
and INTERVAL_SEC=30 (because ±45s spans at most ±1.5 intervals ≈ ±1 interval grace).

Gate T5 criterion M6: legit clients succeed >99.9% under ±45s clock drift.
"""
import asyncio
import time
from dataclasses import dataclass, field
from typing import List

import httpx

from allowlist import validate_target
from sdk.mode2 import Mode2Config, route_url, sign_request


@dataclass
class Mode2LegitResult:
    scenario: str = "mode2_legit"
    started_at: str = ""
    finished_at: str = ""
    total_requests: int = 0
    success_count: int = 0
    failure_count: int = 0
    m6_success_rate_pct: float = 0.0
    drift_offsets_tested: List[int] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "scenario": self.scenario,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "total_requests": self.total_requests,
            "success_count": self.success_count,
            "failure_count": self.failure_count,
            "m6_success_rate_pct": self.m6_success_rate_pct,
            "drift_offsets_tested": self.drift_offsets_tested,
            "errors": self.errors,
        }


async def run(cfg: Mode2Config | None = None) -> Mode2LegitResult:
    """
    Run the Mode 2 legit scenario with clock drift offsets from -45s to +45s.
    Each offset is tested with multiple requests to build a success rate.
    """
    if cfg is None:
        cfg = Mode2Config.from_env("m2-legit-sdk-01")

    validate_target(cfg.gateway_url)

    result = Mode2LegitResult()
    result.started_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    # Test drift offsets: 0, ±10, ±20, ±30, ±44 seconds
    # ±44s is within one interval boundary for INTERVAL_SEC=30 with GRACE=1
    drift_offsets = [0, 10, -10, 20, -20, 30, -30, 44, -44]
    result.drift_offsets_tested = drift_offsets

    PATHS = ["/api/v1/shipments", "/api/v1/manifests", "/api/v1/routes"]

    async with httpx.AsyncClient(timeout=10.0) as client:
        for offset in drift_offsets:
            for path in PATHS:
                try:
                    url, interval = route_url(
                        cfg.gateway_url, path,
                        cfg.secret, cfg.interval_sec,
                        time_offset_sec=offset,
                    )
                    headers = sign_request(
                        cfg.secret, "GET", path, b"",
                        cfg.device_id + f"-drift{offset}",
                    )
                    headers["User-Agent"] = "TCAD-SDK/1.0 mode=2"

                    r = await client.get(url, headers=headers)
                    result.total_requests += 1

                    if 200 <= r.status_code < 300:
                        result.success_count += 1
                    else:
                        result.failure_count += 1
                        result.errors.append(
                            f"drift={offset:+d}s path={path} status={r.status_code}"
                        )
                except Exception as exc:
                    result.total_requests += 1
                    result.failure_count += 1
                    result.errors.append(f"drift={offset:+d}s path={path}: {exc}")

                await asyncio.sleep(0.05)

    total = result.total_requests
    result.m6_success_rate_pct = (
        round(result.success_count / total * 100, 2) if total else 0.0
    )
    result.finished_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    return result
