"""
attacker-sim/main.py
TCAD Mesh — Attacker-Sim Service

Runs as a long-running HTTP server inside the Docker network.
control-api calls POST /run with {"scenario": "..."} to trigger a scenario.
This replaces the previous Docker-SDK launch approach (which required
mounting the Docker socket — a security risk).

Endpoints:
  POST /run       — run a scenario (scan, legit, full)
  GET  /health    — health check
  GET  /status    — current/last run status
"""
import asyncio
import json
import os
import time
from dataclasses import asdict
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from allowlist import validate_target, AllowlistViolation

SERVICE_NAME = "attacker-sim"
VERSION = "0.1.0"

app = FastAPI(title="TCAD Mesh — Attacker-Sim", version=VERSION,
              docs_url=None, redoc_url=None, openapi_url=None)

# ── State ─────────────────────────────────────────────────────────────────────
_run_lock = asyncio.Lock()
_current_status = {"status": "idle", "scenario": None, "result": None,
                    "started_at": None, "finished_at": None}


class RunRequest(BaseModel):
    scenario: str


# ── Health ────────────────────────────────────────────────────────────────────
@app.get("/health")
async def health():
    return {"status": "ok", "service": SERVICE_NAME, "version": VERSION}


@app.get("/status")
async def status():
    return _current_status


# ── Run a scenario ────────────────────────────────────────────────────────────
@app.post("/run")
async def run_scenario(req: RunRequest):
    global _current_status

    if req.scenario not in ("scan", "legit", "full"):
        raise HTTPException(status_code=422,
                            detail={"error": f"unknown scenario: {req.scenario}", "code": 422})

    if _current_status["status"] == "running":
        raise HTTPException(status_code=409,
                             detail={"error": "simulation already running", "code": 409})

    async with _run_lock:
        _current_status = {
            "status": "running",
            "scenario": req.scenario,
            "result": None,
            "started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "finished_at": None,
        }

        try:
            if req.scenario == "scan":
                from scenarios.scan import run
                result = await run()
            elif req.scenario == "legit":
                from scenarios.legit import run
                result = await run()
            else:
                from scenarios.full import run
                result = await run()

            result_dict = result.as_dict()
            _current_status["status"] = "completed"
            _current_status["result"] = result_dict
            _current_status["finished_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

            # Also write to results file if mounted
            results_path = os.environ.get("RESULTS_PATH", "/results/latest.json")
            try:
                os.makedirs(os.path.dirname(results_path) or ".", exist_ok=True)
                with open(results_path, "w") as f:
                    json.dump(result_dict, f, indent=2)
            except Exception:
                pass

            return {"status": "completed", "scenario": req.scenario, "result": result_dict}

        except Exception as exc:
            _current_status["status"] = "failed"
            _current_status["result"] = {"error": str(exc)[:500]}
            _current_status["finished_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            return {"status": "failed", "scenario": req.scenario,
                    "error": str(exc)[:500]}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8004, log_level="info")
