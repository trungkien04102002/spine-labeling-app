from contextlib import asynccontextmanager
from pathlib import Path

import hmac

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
    # Ensure the MySQL schema exists when the server boots.
    init_db()
    # Runs left "running" by a restart are closed out lazily, by the retraining
    # router, which can tell a dead row from a live one. Doing it here would
    # also fire in any other process that opens this database -- the test suite
    # does -- and stamp a run that is genuinely in flight as interrupted.
    yield


app = FastAPI(title="spine-labeling-app", lifespan=lifespan)

_SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


@app.middleware("http")
async def refuse_writes_when_view_only(request: Request, call_next):
    """In view-only mode, only the operator (admin passphrase) may write.

    Added before CORS, so CORS stays the outer layer and the browser can read
    the refusal instead of seeing an opaque network error.
    """
    settings = Settings()
    if settings.view_only and request.method not in _SAFE_METHODS:
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


# The Vite dev frontend is always allowed; extra origins (e.g. a laptop UI
# hitting a directly-exposed remote backend) come from CORS_ORIGINS.
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


# Serve the built frontend from this same app, so one public port serves the
# whole thing. Mounted AFTER the routers above, so every API path still wins;
# only what is left over falls through to the SPA. When dist/ is absent -- local
# development against the Vite dev server, and the test suite -- nothing is
# mounted and the app behaves exactly as before.
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
        """Return the requested file, or index.html so the router handles it.

        The viewer's routes (/viewer/<id>, /models, /admin) exist only in the
        browser, so a hard refresh on one of them asks the server for a path it
        has no file for -- that has to come back as index.html, not a 404.
        """
        if spa_path:
            candidate = (_dist / spa_path).resolve()
            if candidate.is_file() and candidate.is_relative_to(_dist.resolve()):
                return FileResponse(candidate)
        index = _dist / "index.html"
        if not index.is_file():
            raise HTTPException(status_code=404, detail="frontend not built")
        # index.html names the hashed bundles of the current build; a browser
        # that cached it kept running last week's page after an update (seen
        # 2026-10-02). Revalidate it every time; the bundles themselves are
        # content-hashed and stay cacheable.
        return FileResponse(index, headers={"Cache-Control": "no-cache"})
