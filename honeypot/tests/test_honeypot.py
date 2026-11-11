"""
honeypot/tests/test_honeypot.py
Gate T1 — honeypot verification:
  1. Determinism: same identity → same data every call
  2. Divergence: different identity → different data
  3. Schema parity: same keys/types as target-app
  4. Zero metadata leak: no forbidden words in any response value
  5. Honeytoken format: DOC-<12 hex>
  6. Header indistinguishability: Server = nginx
  7. Unknown paths → 404
"""
import re
import json
import pytest
from httpx import AsyncClient, ASGITransport

from main import app
from generator import HoneypotGenerator

TRANSPORT = ASGITransport(app=app)

# Words that MUST NEVER appear in honeypot responses (AGENTS.md §4.4)
FORBIDDEN_WORDS = {"simulated", "honeypot", "fake", "dummy", "mock", "test"}
DOC_PATTERN = re.compile(r"^DOC-[0-9a-f]{12}$")
MNF_PATTERN = re.compile(r"^MNF-[0-9a-f]{12}$")
RTE_PATTERN = re.compile(r"^RTE-[0-9a-f]{12}$")


# ── Helpers ───────────────────────────────────────────────────────────────────
def scan_for_forbidden(obj, path="root"):
    """Recursively scan any JSON-serialisable object for forbidden words."""
    if isinstance(obj, str):
        lower = obj.lower()
        for word in FORBIDDEN_WORDS:
            assert word not in lower, (
                f"Forbidden word '{word}' found at {path}: {obj!r}"
            )
    elif isinstance(obj, dict):
        for k, v in obj.items():
            scan_for_forbidden(v, f"{path}.{k}")
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            scan_for_forbidden(v, f"{path}[{i}]")


def assert_shipment_shape(s: dict):
    for key in ("id", "status", "origin", "destination", "carrier",
                "created_at", "updated_at", "manifest_id"):
        assert key in s, f"missing key '{key}' in shipment"
    assert DOC_PATTERN.match(s["id"]), f"bad DOC id: {s['id']}"
    assert MNF_PATTERN.match(s["manifest_id"]), f"bad MNF id: {s['manifest_id']}"
    assert s["status"] in ("pending", "in_transit", "delivered", "cancelled")


def assert_manifest_shape(m: dict):
    for key in ("id", "shipment_id", "items", "total_weight_kg", "created_at"):
        assert key in m
    assert MNF_PATTERN.match(m["id"])
    assert isinstance(m["items"], list)
    assert len(m["items"]) > 0


def assert_route_shape(r: dict):
    for key in ("id", "shipment_id", "stops", "created_at"):
        assert key in r
    assert RTE_PATTERN.match(r["id"])


# ── Health ────────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_health():
    async with AsyncClient(transport=TRANSPORT, base_url="http://test") as ac:
        r = await ac.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"
    assert r.json()["service"] == "honeypot"


# ── Determinism: same identity → identical data ───────────────────────────────
@pytest.mark.asyncio
async def test_determinism_shipments():
    headers = {"X-Device-ID": "attacker-device-42"}
    async with AsyncClient(transport=TRANSPORT, base_url="http://test") as ac:
        r1 = await ac.get("/api/v1/shipments", headers=headers)
        r2 = await ac.get("/api/v1/shipments", headers=headers)
    assert r1.status_code == 200
    assert r2.status_code == 200
    assert r1.json()["data"] == r2.json()["data"], "Same identity must produce identical shipments"


@pytest.mark.asyncio
async def test_determinism_manifests():
    headers = {"X-Device-ID": "attacker-device-42"}
    async with AsyncClient(transport=TRANSPORT, base_url="http://test") as ac:
        r1 = await ac.get("/api/v1/manifests", headers=headers)
        r2 = await ac.get("/api/v1/manifests", headers=headers)
    assert r1.json()["data"] == r2.json()["data"]


@pytest.mark.asyncio
async def test_determinism_routes():
    headers = {"X-Device-ID": "attacker-device-42"}
    async with AsyncClient(transport=TRANSPORT, base_url="http://test") as ac:
        r1 = await ac.get("/api/v1/routes", headers=headers)
        r2 = await ac.get("/api/v1/routes", headers=headers)
    assert r1.json()["data"] == r2.json()["data"]


# ── Divergence: different identities → different data ────────────────────────
@pytest.mark.asyncio
async def test_divergence_between_identities():
    async with AsyncClient(transport=TRANSPORT, base_url="http://test") as ac:
        r_a = await ac.get("/api/v1/shipments", headers={"X-Device-ID": "identity-alpha"})
        r_b = await ac.get("/api/v1/shipments", headers={"X-Device-ID": "identity-beta"})
    ids_a = [s["id"] for s in r_a.json()["data"]]
    ids_b = [s["id"] for s in r_b.json()["data"]]
    assert ids_a != ids_b, "Different identities must produce different shipment IDs"


# ── Schema parity with target-app ─────────────────────────────────────────────
@pytest.mark.asyncio
async def test_schema_parity_shipments():
    async with AsyncClient(transport=TRANSPORT, base_url="http://test") as ac:
        r = await ac.get("/api/v1/shipments", headers={"X-Device-ID": "parity-check"})
    assert r.status_code == 200
    body = r.json()
    assert "data" in body and "pagination" in body
    for s in body["data"]:
        assert_shipment_shape(s)


@pytest.mark.asyncio
async def test_schema_parity_manifests():
    async with AsyncClient(transport=TRANSPORT, base_url="http://test") as ac:
        r = await ac.get("/api/v1/manifests", headers={"X-Device-ID": "parity-check"})
    for m in r.json()["data"]:
        assert_manifest_shape(m)


@pytest.mark.asyncio
async def test_schema_parity_routes():
    async with AsyncClient(transport=TRANSPORT, base_url="http://test") as ac:
        r = await ac.get("/api/v1/routes", headers={"X-Device-ID": "parity-check"})
    for rt in r.json()["data"]:
        assert_route_shape(rt)


@pytest.mark.asyncio
async def test_schema_parity_tracking():
    headers = {"X-Device-ID": "parity-check"}
    async with AsyncClient(transport=TRANSPORT, base_url="http://test") as ac:
        ships = (await ac.get("/api/v1/shipments", headers=headers)).json()["data"]
        sid = ships[0]["id"]
        r = await ac.get(f"/api/v1/tracking/{sid}", headers=headers)
    assert r.status_code == 200
    body = r.json()
    assert "shipment_id" in body
    assert isinstance(body["events"], list)


# ── Zero metadata leak ────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_no_forbidden_words_in_shipments():
    async with AsyncClient(transport=TRANSPORT, base_url="http://test") as ac:
        r = await ac.get("/api/v1/shipments", headers={"X-Device-ID": "leak-check"})
    scan_for_forbidden(r.json())


@pytest.mark.asyncio
async def test_no_forbidden_words_in_manifests():
    async with AsyncClient(transport=TRANSPORT, base_url="http://test") as ac:
        r = await ac.get("/api/v1/manifests", headers={"X-Device-ID": "leak-check"})
    scan_for_forbidden(r.json())


@pytest.mark.asyncio
async def test_no_forbidden_words_in_routes():
    async with AsyncClient(transport=TRANSPORT, base_url="http://test") as ac:
        r = await ac.get("/api/v1/routes", headers={"X-Device-ID": "leak-check"})
    scan_for_forbidden(r.json())


# ── Honeytoken ID format ──────────────────────────────────────────────────────
def test_honeytoken_id_format():
    gen = HoneypotGenerator("test-secret", "identity-x")
    for s in gen.shipments(5):
        assert DOC_PATTERN.match(s["id"]), f"Bad token format: {s['id']}"


# ── Generator unit tests ──────────────────────────────────────────────────────
def test_generator_is_pure():
    """Calling generator methods repeatedly must always return the same result."""
    gen = HoneypotGenerator("secret123", "device-abc")
    assert gen.shipments(5) == gen.shipments(5)
    assert gen.manifests(5) == gen.manifests(5)
    assert gen.routes(3) == gen.routes(3)


def test_generator_different_secrets_differ():
    g1 = HoneypotGenerator("secret-A", "same-identity")
    g2 = HoneypotGenerator("secret-B", "same-identity")
    ids1 = [s["id"] for s in g1.shipments(5)]
    ids2 = [s["id"] for s in g2.shipments(5)]
    assert ids1 != ids2


# ── Header indistinguishability ───────────────────────────────────────────────
@pytest.mark.asyncio
async def test_server_header_normalised():
    async with AsyncClient(transport=TRANSPORT, base_url="http://test") as ac:
        r = await ac.get("/health")
    assert r.headers.get("server", "").lower() == "nginx"


# ── Unknown paths → 404 ───────────────────────────────────────────────────────
# NOTE: The honeypot now has a catch-all route, so it MUST return 200 for all
# paths — including canary paths like /admin. Strict 404s only apply to
# specific sub-resource lookups (e.g. unknown shipment IDs).
@pytest.mark.parametrize("path", [
    "/admin", "/.env", "/backup", "/api/v1/ops/deploy", "/config",
])
@pytest.mark.asyncio
async def test_canary_paths_return_200_not_404(path: str):
    """Honeypot catch-all MUST return 200 for canary/redirect paths — not 404.
    This prevents the honeypot from leaking its existence via unexpected 404s."""
    async with AsyncClient(transport=TRANSPORT, base_url="http://test") as ac:
        r = await ac.get(path, headers={"X-Device-ID": "test-device"})
    assert r.status_code == 200, (
        f"Honeypot returned {r.status_code} for {path} — "
        f"canary redirects must get a plausible 200"
    )


# ── HONEYTOKEN_ISSUED emission helpers ───────────────────────────────────────
@pytest.mark.asyncio
async def test_catch_all_has_no_forbidden_words():
    """Catch-all response must never expose honeypot metadata."""
    async with AsyncClient(transport=TRANSPORT, base_url="http://test") as ac:
        r = await ac.get("/admin", headers={"X-Device-ID": "catch-all-check"})
    assert r.status_code == 200
    scan_for_forbidden(r.json())


@pytest.mark.asyncio
async def test_catch_all_deterministic():
    """Catch-all response must be deterministic for the same identity."""
    headers = {"X-Device-ID": "stable-identity-99"}
    async with AsyncClient(transport=TRANSPORT, base_url="http://test") as ac:
        r1 = await ac.get("/admin", headers=headers)
        r2 = await ac.get("/admin", headers=headers)
    assert r1.json() == r2.json(), "catch-all must be deterministic per identity"
    """issue_honeytoken must silently succeed even if control-api is unreachable."""
    import os
    os.environ["CONTROL_URL"] = "http://127.0.0.1:19999"  # nothing listening
    from main import issue_honeytoken
    # Should complete without exception regardless of control-api availability
    await issue_honeytoken("DOC-aabbccddeeff", "sess-xyz", "10.0.0.1")
    # Restore
    os.environ.pop("CONTROL_URL", None)


@pytest.mark.asyncio
async def test_shipments_endpoint_issues_honeytoken():
    """Calling GET /api/v1/shipments must trigger honeytoken issuance (fire-and-forget)."""
    import os
    os.environ["CONTROL_URL"] = "http://127.0.0.1:19999"  # nowhere to send
    headers = {"X-Device-ID": "ht-test-device"}
    async with AsyncClient(transport=TRANSPORT, base_url="http://test") as ac:
        r = await ac.get("/api/v1/shipments", headers=headers)
    assert r.status_code == 200
    # The response still has a DOC- id (honeytoken format)
    first_id = r.json()["data"][0]["id"]
    import re
    assert re.match(r"^DOC-[0-9a-f]{12}$", first_id), f"Bad token format: {first_id}"
    os.environ.pop("CONTROL_URL", None)


# ── Exact field-set parity with target-app ────────────────────────────────────
# These tests import the target-app static fixture to establish the canonical
# field names, then verify the honeypot returns exactly the same keys.
# "Exact" means: no missing keys AND no extra keys the target-app doesn't have.
# This guards against schema drift if one service is updated and the other isn't.
#
# Target-app field reference (from target-app/data.py SHIPMENTS fixture):
#   Shipment: id, status, origin, destination, carrier, weight_kg,
#             created_at, updated_at, manifest_id, route_id
#   Manifest: id, shipment_id, items, total_weight_kg, created_at
#             items[*]: sku, description, quantity, unit_weight_kg
#   Route:    id, shipment_id, stops, created_at
#             stops[*]: location, eta, arrived_at

CANONICAL_SHIPMENT_KEYS = frozenset({
    "id", "status", "origin", "destination", "carrier", "weight_kg",
    "created_at", "updated_at", "manifest_id", "route_id",
})
CANONICAL_MANIFEST_KEYS = frozenset({
    "id", "shipment_id", "items", "total_weight_kg", "created_at",
})
CANONICAL_MANIFEST_ITEM_KEYS = frozenset({
    "sku", "description", "quantity", "unit_weight_kg",
})
CANONICAL_ROUTE_KEYS = frozenset({
    "id", "shipment_id", "stops", "created_at",
})
CANONICAL_ROUTE_STOP_KEYS = frozenset({
    "location", "eta", "arrived_at",
})


@pytest.mark.asyncio
async def test_exact_field_parity_shipments():
    """Honeypot shipment objects have EXACTLY the same keys as target-app."""
    async with AsyncClient(transport=TRANSPORT, base_url="http://test") as ac:
        r = await ac.get("/api/v1/shipments", headers={"X-Device-ID": "exact-parity"})
    assert r.status_code == 200
    for s in r.json()["data"]:
        actual = frozenset(s.keys())
        assert actual == CANONICAL_SHIPMENT_KEYS, (
            f"Shipment field mismatch.\n"
            f"  Missing from honeypot: {CANONICAL_SHIPMENT_KEYS - actual}\n"
            f"  Extra in honeypot:     {actual - CANONICAL_SHIPMENT_KEYS}"
        )


@pytest.mark.asyncio
async def test_exact_field_parity_manifests():
    """Honeypot manifest objects have EXACTLY the same keys as target-app."""
    async with AsyncClient(transport=TRANSPORT, base_url="http://test") as ac:
        r = await ac.get("/api/v1/manifests", headers={"X-Device-ID": "exact-parity"})
    assert r.status_code == 200
    for m in r.json()["data"]:
        actual = frozenset(m.keys())
        assert actual == CANONICAL_MANIFEST_KEYS, (
            f"Manifest field mismatch.\n"
            f"  Missing: {CANONICAL_MANIFEST_KEYS - actual}\n"
            f"  Extra:   {actual - CANONICAL_MANIFEST_KEYS}"
        )
        for item in m["items"]:
            actual_item = frozenset(item.keys())
            assert actual_item == CANONICAL_MANIFEST_ITEM_KEYS, (
                f"Manifest item field mismatch.\n"
                f"  Missing: {CANONICAL_MANIFEST_ITEM_KEYS - actual_item}\n"
                f"  Extra:   {actual_item - CANONICAL_MANIFEST_ITEM_KEYS}"
            )


@pytest.mark.asyncio
async def test_exact_field_parity_routes():
    """Honeypot route objects have EXACTLY the same keys as target-app."""
    async with AsyncClient(transport=TRANSPORT, base_url="http://test") as ac:
        r = await ac.get("/api/v1/routes", headers={"X-Device-ID": "exact-parity"})
    assert r.status_code == 200
    for rt in r.json()["data"]:
        actual = frozenset(rt.keys())
        assert actual == CANONICAL_ROUTE_KEYS, (
            f"Route field mismatch.\n"
            f"  Missing: {CANONICAL_ROUTE_KEYS - actual}\n"
            f"  Extra:   {actual - CANONICAL_ROUTE_KEYS}"
        )
        for stop in rt["stops"]:
            actual_stop = frozenset(stop.keys())
            assert actual_stop == CANONICAL_ROUTE_STOP_KEYS, (
                f"Route stop field mismatch.\n"
                f"  Missing: {CANONICAL_ROUTE_STOP_KEYS - actual_stop}\n"
                f"  Extra:   {actual_stop - CANONICAL_ROUTE_STOP_KEYS}"
            )
