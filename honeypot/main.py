"""
honeypot/main.py
TCAD Mesh — Honeypot Service

Rules (AGENTS.md §4.4):
  - Schema MUST exactly match target-app.
  - Data generation seeded with HMAC(HONEYPOT_SECRET, identity).
  - Honeytokens share format DOC-<12 hex>.
  - NEVER include 'simulated', 'honeypot', 'fake', 'pending_*' in responses.
  - Latency jitter 5-15 ms per request.
  - Registers issued honeytokens with control-api (fire-and-forget, non-blocking).
"""
import asyncio
import hashlib
import hmac
import os
import random
import time
import uuid

import httpx
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from generator import HoneypotGenerator

SERVICE_NAME = "honeypot"
VERSION = "0.1.0"
START_TIME = time.time()

HONEYPOT_SECRET = os.environ.get("HONEYPOT_SECRET", "change-me-to-another-random-secret")
CONTROL_URL = os.environ.get("CONTROL_URL", "http://control-api:8003")
INTERNAL_KEY = os.environ.get("INTERNAL_KEY", "change-me-to-a-random-32-char-string")

app = FastAPI(
    title="TCAD Mesh — Honeypot",
    version=VERSION,
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)


# ── Jitter + header normalisation middleware ──────────────────────────────────
class JitterMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        # 5-15 ms latency jitter (AGENTS.md §4.4)
        await asyncio.sleep(random.uniform(0.005, 0.015))
        response = await call_next(request)
        # Header normalisation — indistinguishable from target-app
        response.headers["Server"] = "nginx"
        if "X-Powered-By" in response.headers:
            del response.headers["X-Powered-By"]
        return response


app.add_middleware(JitterMiddleware)


# ── Identity extraction helper ────────────────────────────────────────────────
def get_identity(request: Request) -> str:
    return request.headers.get("X-Device-ID") or request.client.host or "unknown"


# ── Async control-api calls (fire-and-forget, non-blocking) ──────────────────

async def _post_noblock(url: str, payload: dict) -> None:
    """POST to control-api; silently discard ALL errors.
    Gateway MUST NOT crash or slow down if control-api is down (AGENTS.md §4.3)."""
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            await client.post(
                url,
                json=payload,
                headers={"X-Internal-Key": _internal_key()},
            )
    except Exception:
        pass


def _internal_key() -> str:
    """Read key at call time so tests can override env."""
    return os.environ.get("INTERNAL_KEY", INTERNAL_KEY)


def _control_url() -> str:
    """Read URL at call time so tests can override env."""
    return os.environ.get("CONTROL_URL", CONTROL_URL)


async def register_honeytoken(token: str, session_id: str, identity: str) -> None:
    """Register a newly issued honeytoken with control-api (POST /honeytokens)."""
    issued_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    await _post_noblock(
        f"{_control_url()}/honeytokens",
        {"token": token, "session_id": session_id, "identity": identity, "issued_at": issued_at},
    )


async def emit_honeytoken_issued(token: str, session_id: str, identity: str) -> None:
    """Emit a HONEYTOKEN_ISSUED event to control-api (POST /events)."""
    event = {
        "id": str(uuid.uuid4()),
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "event_type": "HONEYTOKEN_ISSUED",
        "severity": "info",
        "mode": 1,
        "src_ip": identity,        # best effort — client IP not available in async context
        "identity": identity,
        "session_id": session_id,
        "method": "GET",
        "path": "/api/v1/shipments",
        "user_agent": "",
        "status": 200,
        "detail": {"token": token},
    }
    await _post_noblock(f"{_control_url()}/events", event)


async def issue_honeytoken(token: str, session_id: str, identity: str) -> None:
    """Register token AND emit HONEYTOKEN_ISSUED event concurrently."""
    await asyncio.gather(
        register_honeytoken(token, session_id, identity),
        emit_honeytoken_issued(token, session_id, identity),
        return_exceptions=True,  # never propagate failures
    )


# ── Health ────────────────────────────────────────────────────────────────────
@app.get("/health")
async def health():
    return {
        "status": "ok",
        "service": SERVICE_NAME,
        "version": VERSION,
        "uptime_seconds": round(time.time() - START_TIME, 1),
    }


# ── Shipments ─────────────────────────────────────────────────────────────────
@app.get("/api/v1/shipments")
async def list_shipments(
    request: Request,
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    status: str = Query(None),
):
    identity = get_identity(request)
    gen = HoneypotGenerator(HONEYPOT_SECRET, identity)
    session_id = request.headers.get("X-Session-ID", str(uuid.uuid4()))

    allowed_statuses = {"pending", "in_transit", "delivered", "cancelled"}
    if status and status not in allowed_statuses:
        raise HTTPException(status_code=400, detail={"error": "bad request", "code": 400})

    shipments = gen.shipments(count=5)
    if status:
        shipments = [s for s in shipments if s["status"] == status]

    # Issue the first shipment ID as a honeytoken — register + emit event (async, non-blocking)
    if shipments:
        asyncio.create_task(
            issue_honeytoken(shipments[0]["id"], session_id, identity)
        )

    return _paginate(shipments, page, limit)


@app.get("/api/v1/shipments/{shipment_id}")
async def get_shipment(shipment_id: str, request: Request):
    identity = get_identity(request)
    gen = HoneypotGenerator(HONEYPOT_SECRET, identity)
    session_id = request.headers.get("X-Session-ID", str(uuid.uuid4()))

    shipments = gen.shipments(count=5)
    for s in shipments:
        if s["id"] == shipment_id:
            asyncio.create_task(
                issue_honeytoken(s["id"], session_id, identity)
            )
            return s

    # Return a deterministic 404-shaped shipment to avoid timing oracle
    raise HTTPException(status_code=404, detail={"error": "resource not found", "code": 404})


# ── Manifests ─────────────────────────────────────────────────────────────────
@app.get("/api/v1/manifests")
async def list_manifests(
    request: Request,
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
):
    identity = get_identity(request)
    gen = HoneypotGenerator(HONEYPOT_SECRET, identity)
    return _paginate(gen.manifests(count=5), page, limit)


@app.get("/api/v1/manifests/{manifest_id}")
async def get_manifest(manifest_id: str, request: Request):
    identity = get_identity(request)
    gen = HoneypotGenerator(HONEYPOT_SECRET, identity)
    for m in gen.manifests(count=5):
        if m["id"] == manifest_id:
            return m
    raise HTTPException(status_code=404, detail={"error": "resource not found", "code": 404})


# ── Routes ────────────────────────────────────────────────────────────────────
@app.get("/api/v1/routes")
async def list_routes(
    request: Request,
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
):
    identity = get_identity(request)
    gen = HoneypotGenerator(HONEYPOT_SECRET, identity)
    return _paginate(gen.routes(count=3), page, limit)


@app.get("/api/v1/routes/{route_id}")
async def get_route(route_id: str, request: Request):
    identity = get_identity(request)
    gen = HoneypotGenerator(HONEYPOT_SECRET, identity)
    for r in gen.routes(count=3):
        if r["id"] == route_id:
            return r
    raise HTTPException(status_code=404, detail={"error": "resource not found", "code": 404})


# ── Tracking ──────────────────────────────────────────────────────────────────
@app.get("/api/v1/tracking/{shipment_id}")
async def get_tracking(shipment_id: str, request: Request):
    identity = get_identity(request)
    gen = HoneypotGenerator(HONEYPOT_SECRET, identity)
    shipments = gen.shipments(count=5)
    for s in shipments:
        if s["id"] == shipment_id:
            return {"shipment_id": shipment_id, "events": gen.tracking(shipment_id)}
    raise HTTPException(status_code=404, detail={"error": "resource not found", "code": 404})


# ── 404 for genuinely unknown paths ──────────────────────────────────────────
# NOTE: This handler fires ONLY for paths that are not registered above AND
# are NOT canary/redirect paths. In normal Tier 1+ operation, the gateway
# never lets a real client reach a truly-unknown honeypot path — it always
# routes via the canary or quarantine path which the catch-all below handles.
# However, for defence-in-depth and schema parity, unknown API sub-paths
# return 404 just like target-app does.
# BUT: canary paths (e.g. /admin, /.env) MUST return 200 — the attacker
# already triggered the canary and is now being served plausible data.
# The catch-all route below handles those.

# ── Catch-all: absorb canary and quarantine redirects ─────────────────────────
# Any path the gateway proxies here (canary hit, quarantine, honeytoken reuse)
# gets a plausible 200 response. This prevents the honeypot from leaking its
# own existence via unexpected 404s on paths like /admin.
@app.api_route("/{full_path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"])
async def catch_all(full_path: str, request: Request):
    """
    Absorb any path the gateway redirects here and return a plausible response.
    Deterministic per identity so repeated requests are consistent.
    NEVER returns words like 'honeypot', 'fake', or 'error' in the body.
    """
    identity = get_identity(request)
    gen = HoneypotGenerator(HONEYPOT_SECRET, identity)
    session_id = request.headers.get("X-Session-ID", str(uuid.uuid4()))

    # Return the shipment list for any unrecognised GET — looks like a real API.
    # For non-GET methods, return a minimal accepted response.
    if request.method in ("POST", "PUT", "PATCH"):
        return JSONResponse(
            status_code=200,
            content={"status": "accepted", "id": gen._hex_id(f"catch:{full_path}")},
        )

    # Default: plausible shipment list (includes a honeytoken)
    shipments = gen.shipments(count=5)
    if shipments:
        asyncio.create_task(
            issue_honeytoken(shipments[0]["id"], session_id, identity)
        )
    return JSONResponse(
        status_code=200,
        content=_paginate(shipments, 1, 20),
    )


@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: Request, exc: RequestValidationError):
    return JSONResponse(
        status_code=400,
        content={"error": "bad request", "code": 400},
    )


# ── Pagination (identical to target-app) ─────────────────────────────────────
def _paginate(data: list, page: int, limit: int) -> dict:
    total = len(data)
    start = (page - 1) * limit
    return {
        "data": data[start: start + limit],
        "pagination": {"page": page, "limit": limit, "total": total},
    }
