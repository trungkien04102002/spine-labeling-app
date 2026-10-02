from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
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
        return FileResponse(index)
