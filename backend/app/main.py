from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.db import init_db
from app.routers import infer, patients, studies


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Ensure the MySQL schema exists when the server boots.
    init_db()
    yield


app = FastAPI(title="spine-labeling-app", lifespan=lifespan)

# Allow the Vite dev frontend (localhost:5173) to call the API from the browser.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_methods=["*"],
    allow_headers=["*"],
)


app.include_router(patients.router)
app.include_router(studies.router)
app.include_router(infer.router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
