# First, before numpy/torch load: size thread pools to the container quota.
import app.cpu_threads  # noqa: F401,I001
from contextlib import asynccontextmanager
from pathlib import Path

import hmac
import re

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.config import Settings
from app.db import init_db
from app.routers import (
    admin,
    feedback,
    full_grading,
    infer,
    patients,
    readers,
    reference_b,
    retraining,
    studies,
    survey,
    trial,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    # Retraining runs left "running" by a restart are closed out lazily by the
    # retraining router. Doing it here would also fire in any other process that
    # opens this database (e.g. tests) and mark a live run as interrupted.
    yield


app = FastAPI(title="spine-labeling-app", lifespan=lifespan)

_SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
# Writes allowed in view-only mode: switching series is browsing, not editing,
# even though it is a PUT that records which series is shown.
_VIEW_ONLY_ALLOWED = re.compile(r"^/studies/[^/]+/active_series$")


@app.middleware("http")
async def refuse_writes_when_view_only(request: Request, call_next):
    """In view-only mode, only the operator (admin passphrase) may write.

    Added before CORS, so CORS stays the outer layer and the browser can read
    the refusal instead of seeing an opaque network error.
    """
    settings = Settings()
    if (
        settings.view_only
        and request.method not in _SAFE_METHODS
        and not _VIEW_ONLY_ALLOWED.match(request.url.path)
    ):
        key = request.headers.get("x-admin-key") or ""
        if not (
            settings.admin_password
            and hmac.compare_digest(key.encode(), settings.admin_password.encode())
        ):
            return JSONResponse(
                {"detail": "This site is view-only: studies cannot be changed here."},
                status_code=403,
            )
    return await call_next(request)


# The Vite dev frontend is always allowed; extra origins come from CORS_ORIGINS.
_origins = ["http://localhost:5173", "http://127.0.0.1:5173"]
_extra = Settings().cors_origins
if _extra:
    _origins += [o.strip() for o in _extra.split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)


app.include_router(admin.router)
app.include_router(patients.router)
app.include_router(readers.router)
app.include_router(studies.router)
app.include_router(infer.router)
app.include_router(full_grading.router)
app.include_router(reference_b.router)
app.include_router(feedback.router)
app.include_router(retraining.router)
app.include_router(survey.router)
app.include_router(trial.router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/app_config")
def app_config() -> dict[str, bool]:
    """What the pages need to know about this deployment before rendering."""
    return {"view_only": Settings().view_only}


# Serve the built frontend from this app. Mounted after the API routers so API
# paths take precedence; nothing is mounted when dist/ is absent (local dev with
# the Vite server, and tests).
_configured = Settings().frontend_dist
_dist = (
    Path(_configured)
    if _configured
    else Path(__file__).resolve().parents[2] / "frontend" / "dist"
)

if (_dist / "index.html").is_file():
    _assets = _dist / "assets"
    if _assets.is_dir():
        app.mount("/assets", StaticFiles(directory=_assets), name="assets")

    @app.get("/{spa_path:path}", include_in_schema=False)
    def serve_frontend(spa_path: str) -> FileResponse:
        """Return the requested file, or index.html for client-side routes.

        Routes such as /viewer/<id> exist only in the browser, so a hard refresh
        must receive index.html rather than a 404.
        """
        if spa_path:
            candidate = (_dist / spa_path).resolve()
            if candidate.is_file() and candidate.is_relative_to(_dist.resolve()):
                return FileResponse(candidate)
        index = _dist / "index.html"
        if not index.is_file():
            raise HTTPException(status_code=404, detail="frontend not built")
        # index.html references the content-hashed bundles of the current build,
        # so it must be revalidated or browsers keep running a stale build after
        # a deploy. The bundles themselves stay cacheable.
        return FileResponse(index, headers={"Cache-Control": "no-cache"})
