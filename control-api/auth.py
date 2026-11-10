"""
control-api/auth.py
X-Internal-Key authentication for write endpoints.
"""
import os
from fastapi import Header, HTTPException, status


def require_internal_key(x_internal_key: str = Header(default="")):
    """FastAPI dependency: raises 403 if X-Internal-Key is wrong or missing.
    Key is read from env at request time so tests can override it."""
    expected = os.environ.get("INTERNAL_KEY", "change-me-to-a-random-32-char-string")
    if not x_internal_key or x_internal_key != expected:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"error": "forbidden", "code": 403},
        )
