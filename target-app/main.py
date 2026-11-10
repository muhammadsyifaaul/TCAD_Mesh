"""
target-app/main.py
TCAD Mesh — Target-App (Mock Logistics API, "Real Backend")
Implements contracts/openapi.yaml with realistic mock data.
Unknown paths return 404 per AGENTS.md §5 anti-pattern rules.
"""
import os
import time
import math
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from starlette.requests import Request
from starlette.responses import Response

from data import (
    SHIPMENTS, MANIFESTS, ROUTES, TRACKING,
    paginate,
)

SERVICE_NAME = "target-app"
VERSION = "0.1.0"
START_TIME = time.time()

app = FastAPI(
    title="TCAD Mesh — Target-App",
    version=VERSION,
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)

# ── Catch-all: unknown paths MUST return 404 (AGENTS.md §5) ──────────────────
@app.middleware("http")
async def strip_server_header(request: Request, call_next):
    response = await call_next(request)
    response.headers["Server"] = "nginx"
    if "X-Powered-By" in response.headers:
        del response.headers["X-Powered-By"]
    return response


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
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    status: str = Query(None),
):
    data = SHIPMENTS
    if status:
        allowed = {"pending", "in_transit", "delivered", "cancelled"}
        if status not in allowed:
            raise HTTPException(status_code=400, detail={"error": f"invalid status '{status}'", "code": 400})
        data = [s for s in data if s["status"] == status]
    return paginate(data, page, limit)


@app.get("/api/v1/shipments/{shipment_id}")
async def get_shipment(shipment_id: str):
    for s in SHIPMENTS:
        if s["id"] == shipment_id:
            return s
    raise HTTPException(status_code=404, detail={"error": "resource not found", "code": 404})


# ── Manifests ─────────────────────────────────────────────────────────────────
@app.get("/api/v1/manifests")
async def list_manifests(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
):
    return paginate(MANIFESTS, page, limit)


@app.get("/api/v1/manifests/{manifest_id}")
async def get_manifest(manifest_id: str):
    for m in MANIFESTS:
        if m["id"] == manifest_id:
            return m
    raise HTTPException(status_code=404, detail={"error": "resource not found", "code": 404})


# ── Routes ────────────────────────────────────────────────────────────────────
@app.get("/api/v1/routes")
async def list_routes(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
):
    return paginate(ROUTES, page, limit)


@app.get("/api/v1/routes/{route_id}")
async def get_route(route_id: str):
    for r in ROUTES:
        if r["id"] == route_id:
            return r
    raise HTTPException(status_code=404, detail={"error": "resource not found", "code": 404})


# ── Tracking ──────────────────────────────────────────────────────────────────
@app.get("/api/v1/tracking/{shipment_id}")
async def get_tracking(shipment_id: str):
    if shipment_id not in TRACKING:
        raise HTTPException(status_code=404, detail={"error": "resource not found", "code": 404})
    return {"shipment_id": shipment_id, "events": TRACKING[shipment_id]}


# ── 404 for every other path ──────────────────────────────────────────────────
@app.exception_handler(404)
async def not_found_handler(request: Request, exc):
    return JSONResponse(
        status_code=404,
        content={"error": "resource not found", "code": 404},
    )


@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: Request, exc: RequestValidationError):
    return JSONResponse(
        status_code=400,
        content={"error": "bad request", "code": 400},
    )
