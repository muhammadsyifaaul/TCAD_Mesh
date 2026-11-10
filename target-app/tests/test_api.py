"""
target-app/tests/test_api.py
Gate T1 — target-app verification:
  - Known paths return 200 with correct schema shapes
  - Unknown paths return 404
  - Missing resource IDs return 404
  - Invalid query params return 400
"""
import pytest
from httpx import AsyncClient, ASGITransport
from main import app
from data import SHIPMENTS, MANIFESTS, ROUTES

TRANSPORT = ASGITransport(app=app)


@pytest.mark.asyncio
async def test_health():
    async with AsyncClient(transport=TRANSPORT, base_url="http://test") as ac:
        r = await ac.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["service"] == "target-app"


# ── Schema shape helpers ───────────────────────────────────────────────────────
def assert_shipment_shape(s: dict):
    for key in ("id", "status", "origin", "destination", "carrier", "created_at", "updated_at", "manifest_id"):
        assert key in s, f"missing key: {key}"
    assert s["id"].startswith("DOC-"), "ID must start with DOC-"
    assert s["status"] in ("pending", "in_transit", "delivered", "cancelled")


def assert_manifest_shape(m: dict):
    for key in ("id", "shipment_id", "items", "total_weight_kg", "created_at"):
        assert key in m
    assert m["id"].startswith("MNF-")
    assert isinstance(m["items"], list)


def assert_route_shape(r: dict):
    for key in ("id", "shipment_id", "stops", "created_at"):
        assert key in r
    assert r["id"].startswith("RTE-")


# ── Shipments ─────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_list_shipments_returns_200_and_pagination():
    async with AsyncClient(transport=TRANSPORT, base_url="http://test") as ac:
        r = await ac.get("/api/v1/shipments")
    assert r.status_code == 200
    body = r.json()
    assert "data" in body
    assert "pagination" in body
    assert body["pagination"]["total"] == len(SHIPMENTS)
    for s in body["data"]:
        assert_shipment_shape(s)


@pytest.mark.asyncio
async def test_list_shipments_filter_by_status():
    async with AsyncClient(transport=TRANSPORT, base_url="http://test") as ac:
        r = await ac.get("/api/v1/shipments?status=delivered")
    assert r.status_code == 200
    for s in r.json()["data"]:
        assert s["status"] == "delivered"


@pytest.mark.asyncio
async def test_list_shipments_invalid_status_returns_400():
    async with AsyncClient(transport=TRANSPORT, base_url="http://test") as ac:
        r = await ac.get("/api/v1/shipments?status=BOGUS")
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_get_shipment_known_id():
    sid = SHIPMENTS[0]["id"]
    async with AsyncClient(transport=TRANSPORT, base_url="http://test") as ac:
        r = await ac.get(f"/api/v1/shipments/{sid}")
    assert r.status_code == 200
    assert_shipment_shape(r.json())
    assert r.json()["id"] == sid


@pytest.mark.asyncio
async def test_get_shipment_unknown_id_returns_404():
    async with AsyncClient(transport=TRANSPORT, base_url="http://test") as ac:
        r = await ac.get("/api/v1/shipments/DOC-000000000000")
    assert r.status_code == 404
    assert r.json()["code"] == 404


# ── Manifests ─────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_list_manifests():
    async with AsyncClient(transport=TRANSPORT, base_url="http://test") as ac:
        r = await ac.get("/api/v1/manifests")
    assert r.status_code == 200
    for m in r.json()["data"]:
        assert_manifest_shape(m)


@pytest.mark.asyncio
async def test_get_manifest_known_id():
    mid = MANIFESTS[0]["id"]
    async with AsyncClient(transport=TRANSPORT, base_url="http://test") as ac:
        r = await ac.get(f"/api/v1/manifests/{mid}")
    assert r.status_code == 200
    assert r.json()["id"] == mid


@pytest.mark.asyncio
async def test_get_manifest_unknown_returns_404():
    async with AsyncClient(transport=TRANSPORT, base_url="http://test") as ac:
        r = await ac.get("/api/v1/manifests/MNF-000000000000")
    assert r.status_code == 404


# ── Routes ────────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_list_routes():
    async with AsyncClient(transport=TRANSPORT, base_url="http://test") as ac:
        r = await ac.get("/api/v1/routes")
    assert r.status_code == 200
    for rt in r.json()["data"]:
        assert_route_shape(rt)


@pytest.mark.asyncio
async def test_get_route_known_id():
    rid = ROUTES[0]["id"]
    async with AsyncClient(transport=TRANSPORT, base_url="http://test") as ac:
        r = await ac.get(f"/api/v1/routes/{rid}")
    assert r.status_code == 200
    assert r.json()["id"] == rid


@pytest.mark.asyncio
async def test_get_route_unknown_returns_404():
    async with AsyncClient(transport=TRANSPORT, base_url="http://test") as ac:
        r = await ac.get("/api/v1/routes/RTE-000000000000")
    assert r.status_code == 404


# ── Tracking ──────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_get_tracking_known_shipment():
    async with AsyncClient(transport=TRANSPORT, base_url="http://test") as ac:
        r = await ac.get("/api/v1/tracking/DOC-1a2b3c4d5e6f")
    assert r.status_code == 200
    body = r.json()
    assert "shipment_id" in body
    assert isinstance(body["events"], list)


@pytest.mark.asyncio
async def test_get_tracking_unknown_returns_404():
    async with AsyncClient(transport=TRANSPORT, base_url="http://test") as ac:
        r = await ac.get("/api/v1/tracking/DOC-000000000000")
    assert r.status_code == 404


# ── 404 for completely unknown paths (AGENTS.md §5 anti-pattern guard) ────────
@pytest.mark.parametrize("path", [
    "/admin",
    "/.env",
    "/backup",
    "/api/v1/ops/deploy",
    "/api/v2/shipments",
    "/config",
    "/metrics",
    "/debug",
    "/wp-admin",
    "/etc/passwd",
])
@pytest.mark.asyncio
async def test_unknown_paths_return_404(path: str):
    async with AsyncClient(transport=TRANSPORT, base_url="http://test") as ac:
        r = await ac.get(path)
    assert r.status_code == 404, f"Expected 404 for {path}, got {r.status_code}"


# ── Pagination ────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_pagination_limit():
    async with AsyncClient(transport=TRANSPORT, base_url="http://test") as ac:
        r = await ac.get("/api/v1/shipments?limit=2&page=1")
    assert r.status_code == 200
    body = r.json()
    assert len(body["data"]) <= 2
    assert body["pagination"]["limit"] == 2
    assert body["pagination"]["page"] == 1


@pytest.mark.asyncio
async def test_server_header_normalised():
    """Response Server header must be normalised, not uvicorn."""
    async with AsyncClient(transport=TRANSPORT, base_url="http://test") as ac:
        r = await ac.get("/health")
    assert r.headers.get("server", "").lower() == "nginx"
