"""
attacker-sim/tests/test_allowlist.py
Gate T3 — allowlist verification:
  - External IPs/domains are REJECTED.
  - Allowed local targets PASS.
  - AllowlistTransport blocks forbidden requests at the transport layer.
"""
import pytest
import httpx
from allowlist import validate_target, AllowlistViolation
from client import make_client, AllowlistTransport


# ── validate_target: ALLOWED cases ───────────────────────────────────────────
@pytest.mark.parametrize("url", [
    "http://gateway:8080/api/v1/shipments",
    "http://localhost:8080/health",
    "http://127.0.0.1:8080/health",
    "http://10.0.0.1:8080/test",
    "http://172.20.0.5:8080/test",
    "http://192.168.1.100:8080/test",
    "http://target-app:8001/health",
    "http://honeypot:8002/health",
    "http://control-api:8003/health",
])
def test_allowed_targets_pass(url: str):
    """All local / Docker-internal targets must be allowed."""
    validate_target(url)  # must not raise


# ── validate_target: REJECTED cases ──────────────────────────────────────────
@pytest.mark.parametrize("url", [
    "http://8.8.8.8/test",
    "http://1.1.1.1/dns",
    "https://google.com/test",
    "https://example.com/api",
    "http://attacker.evil.com/pwn",
    "http://203.0.113.1/test",      # TEST-NET (public)
    "http://198.51.100.1/test",     # TEST-NET (public)
])
def test_external_targets_rejected(url: str):
    """External IPs and public domains MUST be rejected."""
    with pytest.raises(AllowlistViolation):
        validate_target(url)


# ── Edge cases ────────────────────────────────────────────────────────────────
def test_empty_host_rejected():
    with pytest.raises(AllowlistViolation):
        validate_target("http:///path")


def test_unparseable_url_rejected():
    with pytest.raises(AllowlistViolation):
        validate_target("not-a-url-at-all")


def test_ipv6_loopback_allowed():
    validate_target("http://[::1]:8080/health")


# ── make_client validates at construction ─────────────────────────────────────
def test_make_client_rejects_external_base_url():
    with pytest.raises(AllowlistViolation):
        make_client("http://8.8.8.8:80", device_id="test")


def test_make_client_allows_local_base_url():
    client = make_client("http://localhost:8080", device_id="test")
    assert client is not None
    # Cleanup
    import asyncio
    asyncio.get_event_loop().run_until_complete(client.aclose())


# ── AllowlistTransport blocks at send time ────────────────────────────────────
@pytest.mark.asyncio
async def test_transport_blocks_external_request():
    """AllowlistTransport must raise AllowlistViolation even if someone
    bypasses make_client and constructs a request directly."""
    # Use a no-op async transport that would succeed if allowlist didn't block it
    class _NeverReached(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request):
            raise AssertionError("Transport should not be called for blocked requests")

    transport = AllowlistTransport(_NeverReached())
    req = httpx.Request("GET", "http://8.8.8.8/test")
    with pytest.raises(AllowlistViolation):
        await transport.handle_async_request(req)


@pytest.mark.asyncio
async def test_transport_allows_local_request():
    """AllowlistTransport must pass through local requests."""
    class _Mock200(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request):
            return httpx.Response(200)

    transport = AllowlistTransport(_Mock200())
    req = httpx.Request("GET", "http://localhost:8080/health")
    resp = await transport.handle_async_request(req)
    assert resp.status_code == 200


# ── Scenario config only uses allowed URLs ────────────────────────────────────
def test_gateway_url_is_allowed():
    """Config's GATEWAY_URL must always point at an allowed target."""
    from config import GATEWAY_URL
    validate_target(GATEWAY_URL)  # must not raise


def test_control_url_is_allowed():
    from config import CONTROL_URL
    validate_target(CONTROL_URL)
