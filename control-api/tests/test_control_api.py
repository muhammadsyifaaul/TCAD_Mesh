"""
control-api/tests/test_control_api.py
Gate T2 — control-api verification:
  - Health endpoint
  - POST /events (auth, schema validation, dedup)
  - GET /events (filters: since, type, limit)
  - GET /stats
  - Quarantine CRUD + TTL + release
  - Honeytoken registration + list
  - Sim run + conflict + status
  - Auth rejection on all write endpoints
"""
import json
import os
import sqlite3
import tempfile
import time
import uuid
import pytest
from httpx import AsyncClient, ASGITransport

# Set a test-specific DB_PATH before any imports
os.environ["DB_PATH"] = f"/tmp/test_{uuid.uuid4().hex}.db"
os.environ["INTERNAL_KEY"] = "test-internal-key"

from main import app
from db import init_db, get_db, set_shared_test_connection

TRANSPORT = ASGITransport(app=app)
KEY = "test-internal-key"
GOOD_HEADERS = {"X-Internal-Key": KEY}
BAD_HEADERS  = {"X-Internal-Key": "wrong"}


def _event(overrides=None):
    base = {
        "id": "550e8400-e29b-41d4-a716-446655440000",
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),  # MUST be current — GET /events filters > 24h
        "event_type": "CANARY_HIT",
        "severity": "high",
        "mode": 1,
        "src_ip": "10.0.0.1",
        "identity": "device-abc",
        "session_id": "sess-001",
        "method": "GET",
        "path": "/admin",
        "user_agent": "scanner/1.0",
        "status": 200,
        "detail": {"canary_path": "/admin"},
    }
    if overrides:
        base.update(overrides)
    return base


@pytest.fixture(autouse=True)
def fresh_db():
    """Use a shared SQLite connection for test isolation.

    FastAPI sync endpoints run in a thread pool. Each thread gets its own
    thread-local SQLite connection. In WAL mode, each connection sees a
    snapshot from when its transaction started — writes in one thread may
    not be visible to reads in another thread's connection.

    Fix: create a single shared connection (check_same_thread=False) and
    register it via set_shared_test_connection(). All get_db() calls,
    whether from the test thread or the ASGI thread pool, use this one
    connection, ensuring all writes are immediately visible to reads.
    """
    test_db = f"/tmp/test_{uuid.uuid4().hex}.db"
    os.environ["DB_PATH"] = test_db

    # Create a single shared connection for all threads
    conn = sqlite3.connect(test_db, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    set_shared_test_connection(conn)

    # Initialize schema
    init_db()

    # Clean tables
    conn.execute("DELETE FROM events")
    conn.execute("DELETE FROM quarantine")
    conn.execute("DELETE FROM honeytokens")
    conn.execute("DELETE FROM sim_runs")
    conn.commit()

    yield

    # Tear down: remove the shared connection
    set_shared_test_connection(None)
    conn.close()
    try:
        os.unlink(test_db)
    except Exception:
        pass


# ── Health ────────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_health():
    async with AsyncClient(transport=TRANSPORT, base_url="http://test") as ac:
        r = await ac.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


# ── POST /events ──────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_post_event_accepted():
    async with AsyncClient(transport=TRANSPORT, base_url="http://test") as ac:
        r = await ac.post("/events", json=_event(), headers=GOOD_HEADERS)
    assert r.status_code == 202
    assert r.json()["id"] == "550e8400-e29b-41d4-a716-446655440000"


@pytest.mark.asyncio
async def test_post_event_requires_auth():
    async with AsyncClient(transport=TRANSPORT, base_url="http://test") as ac:
        r = await ac.post("/events", json=_event(), headers=BAD_HEADERS)
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_post_event_no_auth_header():
    async with AsyncClient(transport=TRANSPORT, base_url="http://test") as ac:
        r = await ac.post("/events", json=_event())
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_post_event_invalid_type_rejected():
    async with AsyncClient(transport=TRANSPORT, base_url="http://test") as ac:
        r = await ac.post("/events", json=_event({"event_type": "BOGUS"}), headers=GOOD_HEADERS)
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_post_event_deduplication():
    """Same event ID submitted twice must not create a duplicate."""
    async with AsyncClient(transport=TRANSPORT, base_url="http://test") as ac:
        await ac.post("/events", json=_event(), headers=GOOD_HEADERS)
        await ac.post("/events", json=_event(), headers=GOOD_HEADERS)
        r = await ac.get("/events")
    assert r.json()["total"] == 1


# ── GET /events ───────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_get_events_empty():
    async with AsyncClient(transport=TRANSPORT, base_url="http://test") as ac:
        r = await ac.get("/events")
    assert r.status_code == 200
    assert r.json()["data"] == []


@pytest.mark.asyncio
async def test_get_events_filter_by_type():
    canary = _event({"id": "id-001", "event_type": "CANARY_HIT"})
    enum   = _event({"id": "id-002", "event_type": "ENUM_DETECTED", "severity": "warn"})
    async with AsyncClient(transport=TRANSPORT, base_url="http://test") as ac:
        await ac.post("/events", json=canary, headers=GOOD_HEADERS)
        await ac.post("/events", json=enum,   headers=GOOD_HEADERS)
        r = await ac.get("/events?type=CANARY_HIT")
    data = r.json()["data"]
    assert len(data) == 1
    assert data[0]["event_type"] == "CANARY_HIT"


@pytest.mark.asyncio
async def test_get_events_filter_multiple_types():
    async with AsyncClient(transport=TRANSPORT, base_url="http://test") as ac:
        await ac.post("/events", json=_event({"id": "e1", "event_type": "CANARY_HIT"}), headers=GOOD_HEADERS)
        await ac.post("/events", json=_event({"id": "e2", "event_type": "QUARANTINED", "severity": "high"}), headers=GOOD_HEADERS)
        await ac.post("/events", json=_event({"id": "e3", "event_type": "ENUM_DETECTED", "severity": "warn"}), headers=GOOD_HEADERS)
        r = await ac.get("/events?type=CANARY_HIT,QUARANTINED")
    assert r.json()["total"] == 2


@pytest.mark.asyncio
async def test_get_events_limit():
    async with AsyncClient(transport=TRANSPORT, base_url="http://test") as ac:
        for i in range(5):
            await ac.post("/events", json=_event({"id": f"id-{i:03d}"}), headers=GOOD_HEADERS)
        r = await ac.get("/events?limit=3")
    assert len(r.json()["data"]) == 3


# ── GET /stats ────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_stats_empty():
    async with AsyncClient(transport=TRANSPORT, base_url="http://test") as ac:
        r = await ac.get("/stats")
    assert r.status_code == 200
    assert r.json()["total_events"] == 0


@pytest.mark.asyncio
async def test_stats_counts():
    async with AsyncClient(transport=TRANSPORT, base_url="http://test") as ac:
        await ac.post("/events", json=_event({"id": "s1"}), headers=GOOD_HEADERS)
        await ac.post("/events", json=_event({"id": "s2", "event_type": "ENUM_DETECTED", "severity": "warn"}), headers=GOOD_HEADERS)
        r = await ac.get("/stats")
    body = r.json()
    assert body["total_events"] == 2
    assert body["events_by_type"]["CANARY_HIT"] == 1
    assert body["events_by_type"]["ENUM_DETECTED"] == 1


# ── Quarantine ────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_quarantine_add_and_list():
    async with AsyncClient(transport=TRANSPORT, base_url="http://test") as ac:
        r = await ac.post("/quarantine/10.0.0.1",
                          json={"reason": "CANARY_HIT", "ttl_sec": 900},
                          headers=GOOD_HEADERS)
        assert r.status_code == 201
        r2 = await ac.get("/quarantine")
    assert len(r2.json()["data"]) == 1
    entry = r2.json()["data"][0]
    assert entry["identity"] == "10.0.0.1"
    assert entry["reason"] == "CANARY_HIT"
    assert entry["remaining_ttl_sec"] > 0


@pytest.mark.asyncio
async def test_quarantine_duplicate_does_not_reset_ttl():
    async with AsyncClient(transport=TRANSPORT, base_url="http://test") as ac:
        r1 = await ac.post("/quarantine/10.0.0.2",
                           json={"reason": "CANARY_HIT", "ttl_sec": 60},
                           headers=GOOD_HEADERS)
        assert r1.status_code == 201
        r2 = await ac.post("/quarantine/10.0.0.2",
                           json={"reason": "CANARY_HIT", "ttl_sec": 9000},
                           headers=GOOD_HEADERS)
        # Second call must return 200 (not 201) and NOT extend the TTL
        assert r2.status_code == 200
        r3 = await ac.get("/quarantine")
    remaining = r3.json()["data"][0]["remaining_ttl_sec"]
    assert remaining <= 60, f"TTL was reset (remaining={remaining})"


@pytest.mark.asyncio
async def test_quarantine_release():
    async with AsyncClient(transport=TRANSPORT, base_url="http://test") as ac:
        await ac.post("/quarantine/10.0.0.3",
                      json={"reason": "CANARY_HIT", "ttl_sec": 900},
                      headers=GOOD_HEADERS)
        r = await ac.post("/quarantine/10.0.0.3/release", headers=GOOD_HEADERS)
        assert r.status_code == 200
        assert r.json()["released"] is True
        r2 = await ac.get("/quarantine")
    assert len(r2.json()["data"]) == 0


@pytest.mark.asyncio
async def test_quarantine_release_nonexistent_returns_404():
    async with AsyncClient(transport=TRANSPORT, base_url="http://test") as ac:
        r = await ac.post("/quarantine/nobody/release", headers=GOOD_HEADERS)
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_quarantine_requires_auth():
    async with AsyncClient(transport=TRANSPORT, base_url="http://test") as ac:
        r = await ac.post("/quarantine/10.0.0.9",
                          json={"reason": "CANARY_HIT", "ttl_sec": 60},
                          headers=BAD_HEADERS)
    assert r.status_code == 403


# ── Honeytokens ───────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_register_honeytoken():
    async with AsyncClient(transport=TRANSPORT, base_url="http://test") as ac:
        r = await ac.post("/honeytokens",
                          json={"token": "DOC-aabbccddeeff", "session_id": "s1",
                                "identity": "10.0.0.1", "issued_at": "2026-11-08T10:00:00Z"},
                          headers=GOOD_HEADERS)
        assert r.status_code == 201
        assert r.json()["registered"] is True
        r2 = await ac.get("/honeytokens")
    # New contract: tokens is a list of objects, not strings
    token_vals = [t["token"] for t in r2.json()["tokens"]]
    assert "DOC-aabbccddeeff" in token_vals


@pytest.mark.asyncio
async def test_register_honeytoken_returns_full_metadata():
    """GET /honeytokens must return full objects with session_id and identity."""
    payload = {"token": "DOC-aabbccddeeff", "session_id": "sess-test",
               "identity": "victim-device", "issued_at": "2026-11-08T10:00:00Z"}
    async with AsyncClient(transport=TRANSPORT, base_url="http://test") as ac:
        await ac.post("/honeytokens", json=payload, headers=GOOD_HEADERS)
        r = await ac.get("/honeytokens")
    tokens = r.json()["tokens"]
    assert len(tokens) == 1
    assert tokens[0]["token"] == "DOC-aabbccddeeff"
    assert tokens[0]["session_id"] == "sess-test"
    assert tokens[0]["identity"] == "victim-device"


@pytest.mark.asyncio
async def test_register_honeytoken_idempotent():
    payload = {"token": "DOC-112233445566", "session_id": "s2",
               "identity": "10.0.0.1", "issued_at": "2026-11-08T10:00:00Z"}
    async with AsyncClient(transport=TRANSPORT, base_url="http://test") as ac:
        await ac.post("/honeytokens", json=payload, headers=GOOD_HEADERS)
        await ac.post("/honeytokens", json=payload, headers=GOOD_HEADERS)
        r = await ac.get("/honeytokens")
    token_vals = [t["token"] for t in r.json()["tokens"]]
    assert token_vals.count("DOC-112233445566") == 1


@pytest.mark.asyncio
async def test_honeytoken_requires_auth():
    async with AsyncClient(transport=TRANSPORT, base_url="http://test") as ac:
        r = await ac.post("/honeytokens",
                          json={"token": "DOC-000000000000", "session_id": "s",
                                "identity": "x", "issued_at": "2026-11-08T10:00:00Z"})
    assert r.status_code == 403


# ── Quarantine epoch and reset ────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_quarantine_list_includes_epoch():
    async with AsyncClient(transport=TRANSPORT, base_url="http://test") as ac:
        r = await ac.get("/quarantine")
    assert "epoch" in r.json(), "GET /quarantine must include 'epoch' field"
    assert isinstance(r.json()["epoch"], int)


@pytest.mark.asyncio
async def test_reset_bumps_epoch():
    async with AsyncClient(transport=TRANSPORT, base_url="http://test") as ac:
        r1 = await ac.get("/quarantine")
        epoch_before = r1.json()["epoch"]
        await ac.post("/reset", headers=GOOD_HEADERS)
        r2 = await ac.get("/quarantine")
        epoch_after = r2.json()["epoch"]
    assert epoch_after == epoch_before + 1, (
        f"POST /reset must increment epoch: before={epoch_before} after={epoch_after}"
    )


# ── Simulation ────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_sim_run_accepted():
    async with AsyncClient(transport=TRANSPORT, base_url="http://test") as ac:
        r = await ac.post("/sim/run", json={"scenario": "scan"}, headers=GOOD_HEADERS)
    assert r.status_code == 202
    body = r.json()
    assert body["scenario"] == "scan"
    assert body["status"] == "started"
    assert "run_id" in body


@pytest.mark.asyncio
async def test_sim_run_conflict():
    async with AsyncClient(transport=TRANSPORT, base_url="http://test") as ac:
        await ac.post("/sim/run", json={"scenario": "scan"}, headers=GOOD_HEADERS)
        r = await ac.post("/sim/run", json={"scenario": "legit"}, headers=GOOD_HEADERS)
    assert r.status_code == 409


@pytest.mark.asyncio
async def test_sim_run_invalid_scenario():
    async with AsyncClient(transport=TRANSPORT, base_url="http://test") as ac:
        r = await ac.post("/sim/run", json={"scenario": "nuke"}, headers=GOOD_HEADERS)
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_sim_status_idle():
    async with AsyncClient(transport=TRANSPORT, base_url="http://test") as ac:
        r = await ac.get("/sim/status")
    assert r.status_code == 200
    assert r.json()["status"] == "idle"
