"""Operator passphrase guarding the admin endpoints.

A convenience lock, not real security: it keeps clinicians away from other
rooms' data and model switching, but the passphrase travels in a header,
possibly over plain HTTP. With no passphrase configured nothing is locked
(local development and tests).
"""

import hmac

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel

from app.config import Settings, get_settings

router = APIRouter(tags=["admin"])


def require_admin(
    x_admin_key: str | None = Header(default=None),
    settings: Settings = Depends(get_settings),
) -> None:
    """Dependency: raise 401 unless ``X-Admin-Key`` matches the configured passphrase."""
    if not settings.admin_password:
        return
    if x_admin_key is None or not hmac.compare_digest(
        x_admin_key.encode(), settings.admin_password.encode()
    ):
        raise HTTPException(401, "Admin passphrase required.")


@router.get("/admin/status")
def status(settings: Settings = Depends(get_settings)) -> dict[str, bool]:
    """Report whether an admin passphrase is configured."""
    return {"locked": bool(settings.admin_password)}


class LoginIn(BaseModel):
    password: str


@router.post("/admin/login")
def login(payload: LoginIn, settings: Settings = Depends(get_settings)) -> dict[str, bool]:
    """Check a passphrase (401 if wrong); the client then sends it as ``X-Admin-Key``."""
    require_admin(payload.password, settings)
    return {"ok": True}
