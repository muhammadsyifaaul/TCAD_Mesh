"""
control-api/main.py
TCAD Mesh — Control-API (FastAPI + SQLite)
Implements all endpoints from contracts/control-api.md.
"""
import json
import time
import uuid
from datetime import datetime, timezone, timedelta
from typing import Optional

from fastapi import FastAPI, HTTPException, Query, Depends, Request
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError

from auth import require_internal_key
from db import init_db, get_db
from models import EventIn, QuarantineIn, HoneytokenIn, SimRunIn

SERVICE_NAME = "control-api"
VERSION = "0.1.0"
START_TIME = time.time()

app = FastAPI(
    title="TCAD Mesh — Control-API",
    version=VERSION,
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)


@app.on_event("startup")
def startup():
    init_db()


# ── Error handlers ────────────────────────────────────────────────────────────
@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: Request, exc: RequestValidationError):
    return JSONResponse(
        status_code=422,
        content={"error": "validation error", "code": 422, "detail": str(exc)},
    )


# ── Health ────────────────────────────────────────────────────────────────────
@app.get("/health")
def health():
    return {
        "status": "ok",
        "service": SERVICE_NAME,
        "version": VERSION,
        "uptime_seconds": round(time.time() - START_TIME, 1),
    }


# ── Events ────────────────────────────────────────────────────────────────────
@app.post("/events", status_code=202, dependencies=[Depends(require_internal_key)])
def ingest_event(event: EventIn):
    """Ingest a single event from gateway or honeypot."""
    errors = event.validate_domain()
    if errors:
        raise HTTPException(status_code=422, detail={"error": "; ".join(errors), "code": 422})

    detail_json = json.dumps(event.detail or {})
    with get_db() as conn:
        conn.execute(
            """INSERT OR IGNORE INTO events
               (id, ts, event_type, severity, mode, src_ip, identity,
                session_id, method, path, user_agent, status, detail)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                event.id, event.ts, event.event_type, event.severity,
                event.mode, event.src_ip, event.identity, event.session_id,
                event.method, event.path, event.user_agent, event.status,
                detail_json,
            ),
        )
    return {"id": event.id}


@app.get("/events")
def list_events(
    since: Optional[str] = Query(None),
    type: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=1000),
):
    """Fetch events for dashboard with optional filters."""
    # Default: last 24 hours if since not specified
    if since is None:
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).strftime("%Y-%m-%dT%H:%M:%SZ")
    else:
        cutoff = since

    with get_db() as conn:
        if type:
            # Support comma-separated list of types
            types = [t.strip() for t in type.split(",") if t.strip()]
            placeholders = ",".join("?" * len(types))
            rows = conn.execute(
                f"SELECT * FROM events WHERE ts >= ? AND event_type IN ({placeholders}) "
                f"ORDER BY ts DESC LIMIT ?",
                [cutoff] + types + [limit],
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM events WHERE ts >= ? ORDER BY ts DESC LIMIT ?",
                (cutoff, limit),
            ).fetchall()

    events = [_row_to_event(r) for r in rows]
    return {"data": events, "total": len(events)}


# ── Stats ─────────────────────────────────────────────────────────────────────
@app.get("/stats")
def get_stats():
    """Return aggregated summary metrics."""
    with get_db() as conn:
        total = conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]

        type_rows = conn.execute(
            "SELECT event_type, COUNT(*) as cnt FROM events GROUP BY event_type"
        ).fetchall()
        events_by_type = {r["event_type"]: r["cnt"] for r in type_rows}

        now_iso = _now_iso()
        active_q = conn.execute(
            "SELECT COUNT(*) FROM quarantine WHERE expires_at > ?", (now_iso,)
        ).fetchone()[0]

        active_ht = conn.execute(
            "SELECT COUNT(*) FROM honeytokens WHERE active=1"
        ).fetchone()[0]

        # Count HONEYTOKEN_ISSUED events (≥ active_honeytokens: same token may be
        # issued many times if the same quarantined identity hits multiple endpoints,
        # but INSERT OR IGNORE deduplicates the registry by token value).
        ht_issued_events = conn.execute(
            "SELECT COUNT(*) FROM events WHERE event_type='HONEYTOKEN_ISSUED'"
        ).fetchone()[0]

        ht_reused_events = conn.execute(
            "SELECT COUNT(*) FROM events WHERE event_type='HONEYTOKEN_REUSED'"
        ).fetchone()[0]

    return {
        "total_events": total,
        "events_by_type": events_by_type,
        "active_quarantines": active_q,
        "active_honeytokens": active_ht,
        "honeytokens_issued_total": ht_issued_events,
        "honeytokens_reused_total": ht_reused_events,
        "uptime_seconds": round(time.time() - START_TIME, 1),
    }


# ── Quarantine ────────────────────────────────────────────────────────────────
@app.get("/quarantine")
def list_quarantine():
    """List all currently quarantined identities with remaining TTL and epoch."""
    now_iso = _now_iso()
    now_dt = datetime.now(timezone.utc)
    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM quarantine WHERE expires_at > ? ORDER BY quarantined_at DESC",
            (now_iso,),
        ).fetchall()
        epoch = conn.execute(
            "SELECT value FROM metadata WHERE key='quarantine_epoch'"
        ).fetchone()
        epoch_val = epoch[0] if epoch else 0

    result = []
    for r in rows:
        expires_dt = datetime.fromisoformat(r["expires_at"].replace("Z", "+00:00"))
        remaining = max(0, int((expires_dt - now_dt).total_seconds()))
        result.append({
            "identity": r["identity"],
            "quarantined_at": r["quarantined_at"],
            "expires_at": r["expires_at"],
            "remaining_ttl_sec": remaining,
            "reason": r["reason"],
        })
    # Include epoch so gateway can detect POST /reset without inferring from empty list
    return {"epoch": epoch_val, "data": result}


@app.post("/quarantine/{identity}", status_code=201, dependencies=[Depends(require_internal_key)])
def add_quarantine(identity: str, body: QuarantineIn):
    """Add an identity to quarantine. Does NOT reset TTL if already quarantined.
    When called by the operator (via dashboard), emits a QUARANTINED event with
    detail.source='operator' so the event timeline shows the action."""
    now_iso = _now_iso()
    now_dt = datetime.now(timezone.utc)

    with get_db() as conn:
        # Check if already active
        row = conn.execute(
            "SELECT expires_at FROM quarantine WHERE identity=?", (identity,)
        ).fetchone()
        if row:
            expires_dt = datetime.fromisoformat(row["expires_at"].replace("Z", "+00:00"))
            if expires_dt > now_dt:
                # Already quarantined — return 200, do not reset TTL
                return JSONResponse(
                    status_code=200,
                    content={"identity": identity, "expires_at": row["expires_at"]},
                )

        # Insert or replace (handles expired re-quarantine)
        expires_dt = now_dt + timedelta(seconds=body.ttl_sec)
        expires_iso = expires_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
        conn.execute(
            """INSERT OR REPLACE INTO quarantine (identity, quarantined_at, expires_at, reason)
               VALUES (?,?,?,?)""",
            (identity, now_iso, expires_iso, body.reason),
        )
        # Emit a QUARANTINED event so the timeline records the operator action
        import json as _json
        detail_json = _json.dumps({"source": "operator", "reason": body.reason, "ttl_sec": body.ttl_sec})
        conn.execute(
            """INSERT OR IGNORE INTO events
               (id, ts, event_type, severity, mode, src_ip, identity,
                session_id, method, path, user_agent, status, detail)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                str(__import__("uuid").uuid4()),
                now_iso,
                "QUARANTINED",
                "high",
                1,
                "dashboard",    # src_ip — operator action from dashboard
                identity,
                "operator",     # session_id
                "POST",
                f"/quarantine/{identity}",
                "dashboard/operator",
                201,
                detail_json,
            ),
        )

    return {"identity": identity, "expires_at": expires_iso}


@app.post("/quarantine/{identity}/release", dependencies=[Depends(require_internal_key)])
def release_quarantine(identity: str):
    """Operator manually lifts a quarantine."""
    now_iso = _now_iso()
    with get_db() as conn:
        row = conn.execute(
            "SELECT identity FROM quarantine WHERE identity=? AND expires_at > ?",
            (identity, now_iso),
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail={"error": "not quarantined", "code": 404})
        conn.execute("DELETE FROM quarantine WHERE identity=?", (identity,))
    return {"identity": identity, "released": True}


# ── Honeytokens ───────────────────────────────────────────────────────────────
@app.post("/honeytokens", status_code=201, dependencies=[Depends(require_internal_key)])
def register_honeytoken(body: HoneytokenIn):
    """Honeypot registers a newly issued honeytoken."""
    with get_db() as conn:
        conn.execute(
            """INSERT OR IGNORE INTO honeytokens (token, session_id, identity, issued_at, active)
               VALUES (?,?,?,?,1)""",
            (body.token, body.session_id, body.identity, body.issued_at),
        )
    return {"token": body.token, "registered": True}


@app.get("/honeytokens")
def list_honeytokens():
    """Gateway polls to refresh its in-memory token set with full metadata.
    Returns full objects {token, session_id, identity, issued_at} so the gateway
    can populate detail.original_session correctly in HONEYTOKEN_REUSED events.
    (Contract change approved in Tier 5 fix, item 2.)"""
    with get_db() as conn:
        rows = conn.execute(
            "SELECT token, session_id, identity, issued_at FROM honeytokens WHERE active=1"
        ).fetchall()
    return {"tokens": [
        {
            "token":      r["token"],
            "session_id": r["session_id"],
            "identity":   r["identity"],
            "issued_at":  r["issued_at"],
        }
        for r in rows
    ]}


# ── Simulation ────────────────────────────────────────────────────────────────
@app.post("/sim/run", status_code=202, dependencies=[Depends(require_internal_key)])
def sim_run(body: SimRunIn):
    """Trigger an attack simulation by calling the long-running attacker-sim service."""
    err = body.validate_scenario()
    if err:
        raise HTTPException(status_code=422, detail={"error": err, "code": 422})

    with get_db() as conn:
        running = conn.execute(
            "SELECT run_id FROM sim_runs WHERE status='running'"
        ).fetchone()
        if running:
            raise HTTPException(
                status_code=409,
                detail={"error": "simulation already running", "code": 409},
            )

        run_id = str(uuid.uuid4())
        conn.execute(
            """INSERT INTO sim_runs (run_id, scenario, status, started_at)
               VALUES (?,?,'running',?)""",
            (run_id, body.scenario, _now_iso()),
        )

    # Call attacker-sim over HTTP in a background thread (non-blocking)
    import threading
    threading.Thread(
        target=_call_attacker_sim,
        args=(run_id, body.scenario),
        daemon=True,
    ).start()

    return {"run_id": run_id, "scenario": body.scenario, "status": "started"}


def _call_attacker_sim(run_id: str, scenario: str) -> None:
    """
    Background thread: calls the long-running attacker-sim service over HTTP
    (no Docker socket required). Updates sim_runs on completion.
    """
    import os
    import json as _json
    import httpx

    sim_url = os.environ.get("ATTACKER_SIM_URL", "http://attacker-sim:8004")
    try:
        with httpx.Client(timeout=120.0) as client:
            resp = client.post(
                f"{sim_url}/run",
                json={"scenario": scenario},
            )
            data = resp.json()

            if data.get("status") == "completed":
                _update_sim_run(run_id, "completed", data.get("result", {}))
            else:
                _update_sim_run(run_id, "failed",
                                {"error": data.get("error", "unknown failure")})
    except Exception as exc:
        _update_sim_run(run_id, "failed", {"error": str(exc)[:500]})


def _update_sim_run(run_id: str, status: str, result: dict) -> None:
    import json as _json
    try:
        with get_db() as conn:
            conn.execute(
                """UPDATE sim_runs SET status=?, finished_at=?, result=?
                   WHERE run_id=?""",
                (status, _now_iso(), _json.dumps(result), run_id),
            )
    except Exception:
        pass  # best-effort — don't crash the background thread


@app.get("/sim/status")
def sim_status():
    """Current simulation status."""
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM sim_runs ORDER BY started_at DESC LIMIT 1"
        ).fetchone()

    if not row:
        return {
            "run_id": None, "scenario": None, "status": "idle",
            "started_at": None, "finished_at": None, "result": None,
        }
    return dict(row)


@app.post("/reset", dependencies=[Depends(require_internal_key)])
def reset_demo_data():
    """Clear events, quarantine, and honeytokens for a fresh demo state.
    sim_runs is preserved so GET /sim/status still reflects the last run after reset.
    Bumps quarantine_epoch so the gateway can deterministically clear
    its confirmed in-memory quarantines (no 'empty list' inference)."""
    with get_db() as conn:
        conn.execute("DELETE FROM events")
        conn.execute("DELETE FROM quarantine")
        conn.execute("DELETE FROM honeytokens")
        # NOTE: sim_runs is NOT cleared — preserves /sim/status across reset
        # so e2e tests can still poll completion status after the full scenario's
        # own Phase 0 reset.
        conn.execute(
            "UPDATE metadata SET value = value + 1 WHERE key = 'quarantine_epoch'"
        )
        new_epoch = conn.execute(
            "SELECT value FROM metadata WHERE key='quarantine_epoch'"
        ).fetchone()[0]
    return {"status": "ok", "cleared": ["events", "quarantine", "honeytokens"],
            "preserved": ["sim_runs"],
            "quarantine_epoch": new_epoch}


# ── Internal helpers ──────────────────────────────────────────────────────────
def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _row_to_event(r) -> dict:
    d = dict(r)
    try:
        d["detail"] = json.loads(d.get("detail") or "{}")
    except (json.JSONDecodeError, TypeError):
        d["detail"] = {}
    return d
