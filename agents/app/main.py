from pathlib import Path

from fastapi import Depends, FastAPI
from fastapi.responses import FileResponse

from app.auth import require_user

app = FastAPI(title="Sentra Agent Service")

UI_DIR = Path(__file__).parent / "ui"


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/ui")
def ui(_user: str = Depends(require_user)) -> FileResponse:
    return FileResponse(UI_DIR / "index.html")
