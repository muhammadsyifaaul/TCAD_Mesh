"""
attacker-sim/config.py
Configuration and strict target allowlist for the attacker simulator.

AGENTS.md Rule 6: ALL simulated attacks MUST target local containers within
the Docker network ONLY. The simulator MUST reject any non-allowlisted target.
"""
import os
import re
import ipaddress

# ── Allowlist ─────────────────────────────────────────────────────────────────
# Only these hostnames / IP prefixes may be targeted.
# This prevents accidental scanning of external hosts.
ALLOWED_HOSTS = {
    "gateway",          # Docker service name
    "localhost",
    "127.0.0.1",
    "::1",
}
# Allow any address in RFC-1918 private ranges (Docker bridge networks)
ALLOWED_PRIVATE_RANGES = [
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),   # Docker default: 172.17–172.31
    ipaddress.ip_network("192.168.0.0/16"),
]

# ── Runtime config (all from ENV, with safe defaults) ─────────────────────────
GATEWAY_URL    = os.environ.get("GATEWAY_URL",    "http://gateway:8080")
CONTROL_URL    = os.environ.get("CONTROL_URL",    "http://control-api:8003")
INTERNAL_KEY   = os.environ.get("INTERNAL_KEY",   "change-me-to-a-random-32-char-string")
SIM_TIMEOUT    = float(os.environ.get("SIM_TIMEOUT", "8.0"))   # seconds per request
SIM_DELAY      = float(os.environ.get("SIM_DELAY",   "0.1"))   # delay between requests (s)

# ── Wordlists ─────────────────────────────────────────────────────────────────
# Three independent wordlists used by the scan scenario.
CANARY_WORDLIST = [
    "/admin", "/admin/login", "/admin/dashboard", "/admin/users",
    "/administrator", "/admin.php",
]

SECRETS_WORDLIST = [
    "/.env", "/.env.local", "/.env.production", "/.env.backup",
    "/backup", "/backup.zip", "/backup.tar.gz", "/db.sqlite",
    "/config.json", "/config.yml", "/.git/config",
]

OPS_WORDLIST = [
    "/api/v1/ops/deploy", "/api/v1/ops/config", "/api/v1/ops/shutdown",
    "/actuator", "/actuator/health", "/actuator/env",
    "/metrics", "/debug", "/debug/vars", "/debug/pprof",
    "/swagger.json", "/openapi.json", "/graphql",
]

# Random 404-generating paths for enumeration detection trigger
ENUM_WORDLIST = [
    "/api/v99/shipments",
    "/api/v1/users",
    "/api/v1/orders",
    "/api/v1/products",
    "/api/v1/invoices",
    "/api/v1/internal",
    "/api/v1/secret",
    "/nonexistent-path-alpha",
    "/nonexistent-path-beta",
    "/nonexistent-path-gamma",
]

# Legit API paths that should never trigger any alert
LEGIT_PATHS = [
    "/health",
    "/api/v1/shipments",
    "/api/v1/shipments?page=1&limit=5",
    "/api/v1/manifests",
    "/api/v1/routes",
]
