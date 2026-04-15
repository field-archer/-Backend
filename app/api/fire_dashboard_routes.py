from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.deps import get_current_user
from app.database import get_db
from app.models.fire_marker import FireMarker
from app.models.user import User

router = APIRouter(prefix="/fire-dashboard", tags=["fire-dashboard"])


def _date_range_30d(today: date) -> list[date]:
    start = today - timedelta(days=29)
    return [start + timedelta(days=i) for i in range(30)]


@router.get("")
def get_fire_dashboard(
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    day_start = datetime(now.year, now.month, now.day, tzinfo=timezone.utc)
    day_end = day_start + timedelta(days=1)

    today_reported = db.execute(
        select(func.count()).select_from(FireMarker).where(
            FireMarker.marked_at >= day_start,
            FireMarker.marked_at < day_end,
        )
    ).scalar_one()

    status_rows = db.execute(
        select(FireMarker.status, func.count()).group_by(FireMarker.status)
    ).all()
    status_counts = {str(k): int(v) for k, v in status_rows}

    level_rows = db.execute(
        select(FireMarker.level, func.count()).group_by(FireMarker.level)
    ).all()
    level_counts = {str(k): int(v) for k, v in level_rows}

    cause_rows = db.execute(
        select(FireMarker.cause, func.count()).group_by(FireMarker.cause)
    ).all()
    cause_counts = {str(k): int(v) for k, v in cause_rows}

    cause_name_map = {
        "human": "人为用火",
        "lightning": "雷击火",
        "farming": "农事用火",
        "unknown": "其他未知原因",
    }
    cause_pie = [
        {"name": cause_name_map.get(k, str(k)), "value": int(v)}
        for k, v in cause_counts.items()
    ]

    disposal_name_map = {
        "pending": "待核查",
        "handling": "处置中",
        "extinguished": "已扑灭",
    }
    disposal_pie = [
        {"name": disposal_name_map.get(k, str(k)), "value": int(v)}
        for k, v in status_counts.items()
        if k in disposal_name_map
    ]
    disposal_pie.append({"name": "误报", "value": 0})

    region_rows = db.execute(
        select(FireMarker.region, func.count())
        .where(FireMarker.region.is_not(None), FireMarker.region != "")
        .group_by(FireMarker.region)
        .order_by(func.count().desc())
        .limit(20)
    ).all()
    region_bar = [{"name": str(k), "value": int(v)} for k, v in region_rows]

    today = now.date()
    start_30d = day_start - timedelta(days=29)
    trend_rows = db.execute(
        select(func.date(FireMarker.marked_at), func.count())
        .where(FireMarker.marked_at >= start_30d, FireMarker.marked_at < day_end)
        .group_by(func.date(FireMarker.marked_at))
        .order_by(func.date(FireMarker.marked_at))
    ).all()
    trend_map = {d: int(c) for d, c in trend_rows}
    trend_30d = [
        {"date": d.strftime("%m-%d"), "value": trend_map.get(d, 0)}
        for d in _date_range_30d(today)
    ]

    data = {
        "overview": {
            "today_reported": int(today_reported),
            "pending": int(status_counts.get("pending", 0)),
            "handling": int(status_counts.get("handling", 0)),
            "extinguished": int(status_counts.get("extinguished", 0)),
            "level_counts": {
                "low": int(level_counts.get("low", 0)),
                "medium": int(level_counts.get("medium", 0)),
                "high": int(level_counts.get("high", 0)),
            },
        },
        "cause_pie": cause_pie,
        "disposal_pie": disposal_pie,
        "region_bar": region_bar,
        "trend_30d": trend_30d,
    }
    return {"code": 20000, "message": "成功", "data": data}

