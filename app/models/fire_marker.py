from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import DateTime, Enum, ForeignKey, Index, Integer, Numeric, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class FireMarker(Base):
    __tablename__ = "fire_markers"
    __table_args__ = (Index("ix_fire_markers_user_marked", "user_id", "marked_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    longitude: Mapped[Decimal] = mapped_column(Numeric(12, 8), nullable=False)
    latitude: Mapped[Decimal] = mapped_column(Numeric(12, 8), nullable=False)
    marked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    fire_count: Mapped[int] = mapped_column(Integer, nullable=False)
    source: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    status: Mapped[str] = mapped_column(
        Enum("pending", "handling", "extinguished", name="fire_marker_status"),
        nullable=False,
        server_default="pending",
        index=True,
    )
    level: Mapped[str] = mapped_column(
        Enum("low", "medium", "high", name="fire_marker_level"),
        nullable=False,
        server_default="low",
    )
    cause: Mapped[str] = mapped_column(
        Enum("human", "lightning", "farming", "unknown", name="fire_marker_cause"),
        nullable=False,
        server_default="unknown",
    )
    region: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    reporter_user_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)
    reporter_username: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        index=True,
    )

    user: Mapped["User"] = relationship("User", back_populates="markers")
