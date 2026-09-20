from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import Settings
from app.db import init_db
from app.routers import (
    feedback,
    full_grading,
    infer,
    patients,
    retraining,
    studies,
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


app.include_router(patients.router)
app.include_router(studies.router)
app.include_router(infer.router)
app.include_router(full_grading.router)
app.include_router(feedback.router)
app.include_router(retraining.router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
