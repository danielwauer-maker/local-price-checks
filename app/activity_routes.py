from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field, model_validator
from sqlalchemy.orm import Session

from .activity_service import FEATURES, PAGE_FIELDS, record_client_activity
from .client_context import get_client_key
from .client_models import UserClient
from .db import get_db
from .services import current_user

router = APIRouter(prefix="/api/client")


class ClientActivityPayload(BaseModel):
    kind: Literal["page_view", "pulse", "feature"]
    page: str | None = Field(default=None, max_length=30)
    feature: str | None = Field(default=None, max_length=50)

    @model_validator(mode="after")
    def validate_allow_lists(self):
        if self.page is not None and self.page not in PAGE_FIELDS:
            self.page = "other"
        if self.kind == "feature":
            if not self.feature or self.feature not in FEATURES:
                raise ValueError("unsupported feature")
        else:
            self.feature = None
        return self


@router.post("/activity")
def client_activity(payload: ClientActivityPayload, db: Session = Depends(get_db)):
    user = current_user(db)
    client_key = get_client_key()
    client = db.query(UserClient).filter(UserClient.client_key == client_key).first() if client_key else None
    if client is None:
        return {"ok": False, "reason": "client_not_found"}

    result = record_client_activity(
        db,
        client=client,
        user_id=user.id,
        kind=payload.kind,
        page=payload.page,
        feature=payload.feature,
    )
    return {"ok": True, **result}
