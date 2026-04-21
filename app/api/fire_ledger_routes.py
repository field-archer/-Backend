from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.deps import get_current_user
from app.database import get_db
from app.models.fire_marker import FireMarker
from app.models.fire_marker_event import FireMarkerEvent
from app.models.user import User

router = APIRouter(prefix="/fire-ledger", tags=["fire-ledger"])


@router.get("")
def list_fire_ledger(
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
) -> dict[str, Any]:
    total = db.execute(select(func.count()).select_from(FireMarkerEvent)).scalar_one()
    rows = db.execute(
        select(FireMarkerEvent, FireMarker)
        .join(FireMarker, FireMarkerEvent.marker_id == FireMarker.id)
        .order_by(FireMarkerEvent.event_time.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()

    items = []
    for ev, mk in rows:
        items.append(
            {
                "id": ev.id,
                "marker_id": ev.marker_id,
                "region": ev.region,
                "status": ev.status,
                "level": ev.level,
                "updated_at": ev.event_time,
                "reporter_username": ev.reporter_username,
                "longitude": float(mk.longitude),
                "latitude": float(mk.latitude),
            }
        )
    return {
        "code": 20000,
        "message": "成功",
        "data": {
            "items": items,
            "total": int(total),
            "page": page,
            "page_size": page_size,
        },
    }

