"""
attacker-sim/allowlist.py
Strict target allowlist enforcement (AGENTS.md Rule 6).

validate_target() raises AllowlistViolation for any non-permitted host.
All scenario runners call this before making any HTTP request.
"""
import ipaddress
import re
from urllib.parse import urlparse

from config import ALLOWED_HOSTS, ALLOWED_PRIVATE_RANGES


class AllowlistViolation(Exception):
    """Raised when a target URL is not on the approved allowlist."""
    pass


def validate_target(url: str) -> None:
    """
    Validates that url points at an allowlisted target.
    Raises AllowlistViolation if the host is not permitted.

    Rules (in order):
      1. Known safe hostnames (gateway, localhost) → ALLOW
      2. Loopback addresses → ALLOW
      3. RFC-1918 private IP ranges → ALLOW
      4. Everything else → DENY
    """
    try:
        parsed = urlparse(url)
        host = parsed.hostname or ""
    except Exception as exc:
        raise AllowlistViolation(f"Unparseable URL {url!r}: {exc}") from exc

    if not host:
        raise AllowlistViolation(f"No host found in URL: {url!r}")

    # Rule 1: explicit allowlist of service names / localhost variants
    if host.lower() in ALLOWED_HOSTS:
        return

    # Rule 2 & 3: try parsing as IP address
    try:
        addr = ipaddress.ip_address(host)
        if addr.is_loopback:
            return
        for net in ALLOWED_PRIVATE_RANGES:
            if addr in net:
                return
        raise AllowlistViolation(
            f"IP {host} is not in an allowed private range. "
            f"Simulator MUST only target local containers (AGENTS.md Rule 6)."
        )
    except ValueError:
        pass  # Not an IP — check hostname patterns

    # Hostnames that look like Docker service names on internal network are allowed
    # (single-label hostnames without dots, e.g. "gateway", "target-app")
    if re.match(r'^[a-z][a-z0-9\-]*$', host.lower()) and '.' not in host:
        return

    raise AllowlistViolation(
        f"Host {host!r} is not on the simulator allowlist. "
        f"Only local Docker service names and RFC-1918 addresses are permitted."
    )
