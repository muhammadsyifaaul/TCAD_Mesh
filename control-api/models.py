"""
control-api/models.py
Pydantic models matching contracts/events.schema.json and control-api.md.
"""
from __future__ import annotations
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


# ── Event ─────────────────────────────────────────────────────────────────────
ALLOWED_EVENT_TYPES = {
    "SYSTEM_START", "ENUM_DETECTED", "TARPIT_ACTIVE", "TARPIT_SATURATED",
    "CANARY_HIT", "QUARANTINED", "QUARANTINE_RELEASED", "HONEYTOKEN_ISSUED",
    "HONEYTOKEN_REUSED", "SIM_STARTED", "SIM_FINISHED",
    "TRIPWIRE_HIT", "REPLAY_REJECTED",
}
ALLOWED_SEVERITIES = {"info", "warn", "high"}
ALLOWED_METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS", "TRACE", "CONNECT"}


class EventIn(BaseModel):
    id: str
    ts: str
    event_type: str
    severity: str
    mode: int = 1
    src_ip: str
    identity: str = Field(..., max_length=128)
    session_id: str = Field(..., max_length=128)
    method: str
    path: str = Field(..., max_length=256)
    user_agent: str = Field(default="", max_length=200)
    status: int = Field(..., ge=100, le=599)
    detail: Optional[Dict[str, Any]] = None

    def validate_domain(self):
        errors = []
        if self.event_type not in ALLOWED_EVENT_TYPES:
            errors.append(f"unknown event_type: {self.event_type}")
        if self.severity not in ALLOWED_SEVERITIES:
            errors.append(f"unknown severity: {self.severity}")
        if self.method not in ALLOWED_METHODS:
            errors.append(f"unknown method: {self.method}")
        if self.mode not in (1, 2):
            errors.append(f"mode must be 1 or 2")
        return errors


# ── Quarantine ────────────────────────────────────────────────────────────────
class QuarantineIn(BaseModel):
    reason: str
    ttl_sec: int = Field(default=900, ge=1)


class QuarantineEntry(BaseModel):
    identity: str
    quarantined_at: str
    expires_at: str
    remaining_ttl_sec: int
    reason: str


# ── Honeytoken ────────────────────────────────────────────────────────────────
class HoneytokenIn(BaseModel):
    token: str
    session_id: str
    identity: str
    issued_at: str


# ── Simulation ────────────────────────────────────────────────────────────────
ALLOWED_SCENARIOS = {"scan", "legit", "full"}


class SimRunIn(BaseModel):
    scenario: str

    def validate_scenario(self):
        if self.scenario not in ALLOWED_SCENARIOS:
            return f"scenario must be one of: {', '.join(sorted(ALLOWED_SCENARIOS))}"
        return None
