from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from .config import settings

router = APIRouter()
MEDIA_DIR = settings.data_dir / "admin_media"


@router.get("/media/{filename}")
def public_media(filename: str):
    safe = Path(filename).name
    target = MEDIA_DIR / safe
    if not target.exists() or not target.is_file():
        raise HTTPException(404, "Datei nicht gefunden")
    return FileResponse(target)
