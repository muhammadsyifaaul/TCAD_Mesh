"""
attacker-sim/sdk/mode2.py
Legit-client SDK for Mode 2 (Time-based MTD routing).

Mirrors the gateway's mode2.go logic exactly:
  - DeriveMAC16: HMAC-SHA256(MODE2_SECRET, "route:" + interval_str)[:16 hex]
  - CurrentInterval: floor(unix_time / INTERVAL_SEC)
  - RouteURL: builds /m/<interval>-<mac16>/<canonical_path>
  - SignRequest: adds X-Device-ID, X-Timestamp, X-Nonce, X-Signature headers
  - X-Signature = HMAC-SHA256(secret, method|path|sha256(body)|timestamp|nonce)

Clock drift: the SDK accepts a `time_offset_sec` parameter so tests can
simulate ±45s drift without modifying system time.
"""
import hashlib
import hmac as _hmac
import math
import os
import time
import uuid
from dataclasses import dataclass


# ── Core cryptographic helpers ────────────────────────────────────────────────

def derive_mac16(secret: str, interval: int) -> str:
    """
    HMAC-SHA256(secret, 'route:<interval>') — first 16 hex chars, lower-case.
    Deterministic, O(1).
    """
    msg = f"route:{interval}".encode()
    sig = _hmac.new(secret.encode(), msg, hashlib.sha256).hexdigest()
    return sig[:16]


def current_interval(interval_sec: int, time_offset_sec: float = 0.0) -> int:
    """
    floor((unix_time + offset) / interval_sec)
    offset allows simulating clock drift without touching system time.
    """
    return math.floor((time.time() + time_offset_sec) / interval_sec)


def route_url(base_url: str, canonical_path: str, secret: str,
              interval_sec: int, time_offset_sec: float = 0.0) -> tuple[str, int]:
    """
    Build the Mode 2 routed URL and return (url, interval).
    Interval is calculated ONCE here and reused for the signature.
    """
    interval = current_interval(interval_sec, time_offset_sec)
    mac = derive_mac16(secret, interval)
    canon = canonical_path if canonical_path.startswith("/") else "/" + canonical_path
    url = f"{base_url.rstrip('/')}/m/{interval}-{mac}{canon}"
    return url, interval


def sign_request(
    secret: str,
    method: str,
    canonical_path: str,
    body: bytes,
    device_id: str,
    *,
    nonce: str | None = None,
    timestamp: str | None = None,
) -> dict:
    """
    Compute all anti-replay headers for a Mode 2 request.
    Returns a dict of headers to merge into the request.

    X-Signature = HMAC-SHA256(secret, method|path|sha256(body)|timestamp|nonce)
    """
    if nonce is None:
        nonce = uuid.uuid4().hex
    if timestamp is None:
        timestamp = str(int(time.time()))

    body_sha = hashlib.sha256(body or b"").hexdigest()
    msg = f"{method}|{canonical_path}|{body_sha}|{timestamp}|{nonce}"
    sig = _hmac.new(secret.encode(), msg.encode(), hashlib.sha256).hexdigest()

    return {
        "X-Device-ID": device_id,
        "X-Timestamp": timestamp,
        "X-Nonce":     nonce,
        "X-Signature": sig,
    }


# ── SDK client config ─────────────────────────────────────────────────────────

@dataclass
class Mode2Config:
    gateway_url:   str
    secret:        str
    interval_sec:  int
    grace:         int
    device_id:     str

    @classmethod
    def from_env(cls, device_id: str = "sdk-client-01") -> "Mode2Config":
        return cls(
            gateway_url  = os.environ.get("GATEWAY_URL", "http://gateway:8080"),
            secret       = os.environ.get("MODE2_SECRET", "change-me-mode2-secret"),
            interval_sec = int(os.environ.get("MODE2_INTERVAL_SEC", "30")),
            grace        = int(os.environ.get("MODE2_GRACE", "1")),
            device_id    = device_id,
        )
