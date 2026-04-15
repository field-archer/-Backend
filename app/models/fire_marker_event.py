from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class FireMarkerEvent(Base):
    __tablename__ = "fire_marker_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    marker_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("fire_markers.id", ondelete="CASCADE"), index=True
    )
    region: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(
        Enum("pending", "handling", "extinguished", name="fire_marker_status"),
        nullable=False,
    )
    level: Mapped[str] = mapped_column(
        Enum("low", "medium", "high", name="fire_marker_level"),
        nullable=False,
    )
    reporter_username: Mapped[str] = mapped_column(String(64), nullable=False)
    event_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)

    marker: Mapped["FireMarker"] = relationship("FireMarker")

