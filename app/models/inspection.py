from datetime import datetime
from typing import Any, TYPE_CHECKING
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, Float, ForeignKey, Index, Integer, JSON, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.common import UUIDTimestampMixin

if TYPE_CHECKING:
    from app.models.asset import Asset
    from app.models.media import Media


class Inspection(UUIDTimestampMixin, Base):
    __tablename__ = "inspections"
    __table_args__ = (
        CheckConstraint("confidence >= 0 AND confidence <= 1", name="ck_inspection_confidence"),
        CheckConstraint("severity >= 0 AND severity <= 100", name="ck_inspection_severity"),
        Index("ix_inspections_asset_observed", "asset_id", "observed_at"),
    )

    asset_id: Mapped[UUID] = mapped_column(
        ForeignKey("assets.id", ondelete="CASCADE"), index=True
    )
    media_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("media.id", ondelete="CASCADE"), index=True
    )
    observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
    condition: Mapped[str] = mapped_column(String(32), index=True)
    defect_type: Mapped[str | None] = mapped_column(String(128), index=True)
    confidence: Mapped[float] = mapped_column(Float)
    severity: Mapped[int] = mapped_column(Integer, default=0)
    recommendation: Mapped[str | None] = mapped_column(Text)
    bbox: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    model_name: Mapped[str | None] = mapped_column(String(128))
    model_version: Mapped[str | None] = mapped_column(String(64))
    reviewed: Mapped[bool] = mapped_column(default=False, index=True)

    asset: Mapped["Asset"] = relationship(back_populates="inspections")
    media: Mapped["Media | None"] = relationship(back_populates="inspections")
