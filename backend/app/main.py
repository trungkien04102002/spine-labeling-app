from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.routers import studies

app = FastAPI(title="spine-labeling-app")

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


app.include_router(studies.router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
