"""FastAPI entry point for the demo dashboard (skeleton)."""

from fastapi import FastAPI

from medagent_hospital.config import get_settings

app = FastAPI(title="MedAgent-Hospital", version="0.1.0")


@app.get("/api/health")
def health() -> dict:
    settings = get_settings()
    return {"status": "ok", "llm_backend": settings.llm_backend}
