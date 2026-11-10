"""
attacker-sim/client.py
Shared httpx client factory.  Every scenario must use make_client() to ensure
the allowlist is validated on every request via the custom transport hook.
"""
import time
import httpx
from allowlist import validate_target, AllowlistViolation


class AllowlistTransport(httpx.AsyncBaseTransport):
    """
    Wraps the real transport and validates every request URL against the
    allowlist before sending.  This is the last-resort safety net — scenarios
    also call validate_target() explicitly at startup.
    """
    def __init__(self, wrapped: httpx.AsyncBaseTransport):
        self._wrapped = wrapped

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        validate_target(str(request.url))
        return await self._wrapped.handle_async_request(request)


def make_client(
    base_url: str,
    device_id: str,
    timeout: float = 8.0,
    extra_headers: dict | None = None,
) -> httpx.AsyncClient:
    """
    Create an AsyncClient that:
      - Validates the base_url against the allowlist
      - Sets X-Device-ID for identity tracking
      - Adds a realistic User-Agent
      - Times out quickly enough that the tarpit delay is measurable
    """
    validate_target(base_url)   # fail fast at client creation

    headers = {
        "User-Agent": f"TCAD-Sim/1.0 device={device_id}",
        "X-Device-ID": device_id,
        **(extra_headers or {}),
    }
    transport = AllowlistTransport(httpx.AsyncHTTPTransport(retries=0))
    return httpx.AsyncClient(
        base_url=base_url,
        headers=headers,
        timeout=timeout,
        transport=transport,
        follow_redirects=False,
    )
