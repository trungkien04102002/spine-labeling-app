from fastapi import FastAPI

app = FastAPI(title="spine-labeling-app")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
