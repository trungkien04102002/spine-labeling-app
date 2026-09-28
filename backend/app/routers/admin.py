"""The operator's lock: one passphrase in front of the pages clinicians skip.

A convenience lock, not security. It keeps a clinician who wanders to /admin
from seeing other clinicians' rooms and answers, or switching the model that
grades everyone. The passphrase travels in a header over whatever the box
serves -- plain HTTP unless a tunnel adds TLS -- so it stops curiosity, not an
attacker. With no passphrase configured nothing is locked, which keeps local
development and the tests unchanged.
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
    if not settings.admin_password:
        return
    # Constant-time comparison: cheap, and there is no reason not to.
    if x_admin_key is None or not hmac.compare_digest(
        x_admin_key.encode(), settings.admin_password.encode()
    ):
        raise HTTPException(401, "Admin passphrase required.")


@router.get("/admin/status")
def status(settings: Settings = Depends(get_settings)) -> dict[str, bool]:
    """Whether the operator pages are locked at all."""
    return {"locked": bool(settings.admin_password)}


class LoginIn(BaseModel):
    password: str


@router.post("/admin/login")
def login(payload: LoginIn, settings: Settings = Depends(get_settings)) -> dict[str, bool]:
    """Check a passphrase. The client keeps it and sends it as X-Admin-Key."""
    require_admin(payload.password, settings)
    return {"ok": True}
