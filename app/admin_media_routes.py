from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from .admin_learning import audit
from .admin_routes import MEDIA_DIR, _admin
from .db import get_db
from .models import MediaAsset, MediaAssetMetadata

router = APIRouter()


@router.post("/admin/media/{media_id}/delete")
def delete_media(
    media_id: int,
    db: Session = Depends(get_db),
    actor: str = Depends(_admin),
):
    row = db.get(MediaAsset, media_id)
    if not row:
        raise HTTPException(404, "Medium nicht gefunden")

    local_file = None
    if row.file_path:
        safe_name = Path(row.file_path).name
        local_file = MEDIA_DIR / safe_name

    audit(
        db,
        "media_deleted",
        "media",
        row.id,
        f"kind={row.kind}; retailer={row.retailer or '-'}; file={row.file_path or '-'}; url={row.source_url or '-'}",
        actor,
    )
    db.query(MediaAssetMetadata).filter(
        MediaAssetMetadata.media_asset_id == row.id
    ).delete(synchronize_session=False)
    db.delete(row)
    db.commit()

    if local_file and local_file.exists() and local_file.is_file():
        try:
            local_file.unlink()
        except OSError:
            # The database deletion is authoritative; a filesystem cleanup
            # failure must not restore or duplicate the media record.
            pass

    return RedirectResponse("/admin?tab=media", status_code=303)
