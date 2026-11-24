from datetime import datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.common import UUIDTimestampMixin

if TYPE_CHECKING:
    from app.models.entity import Entity
    from app.models.job import ProcessingJob
    from app.models.media import Media
    from app.models.workspace import Workspace


class Finding(UUIDTimestampMixin, Base):
    """A generic model or human-produced observation/result."""

    __tablename__ = "findings"
    __table_args__ = (
        CheckConstraint(
            "score IS NULL OR (score >= 0 AND score <= 1)", name="ck_finding_score"
        ),
        Index("ix_findings_workspace_status", "workspace_id", "status"),
        Index("ix_findings_entity_observed", "entity_id", "observed_at"),
    )

    workspace_id: Mapped[UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    entity_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("entities.id", ondelete="SET NULL"), index=True
    )
    media_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("media.id", ondelete="SET NULL"), index=True
    )
    job_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("processing_jobs.id", ondelete="SET NULL"), index=True
    )
    observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
    category: Mapped[str] = mapped_column(String(128), index=True)
    label: Mapped[str | None] = mapped_column(String(255), index=True)
    status: Mapped[str | None] = mapped_column(String(64), index=True)
    score: Mapped[float | None] = mapped_column(Float)
    severity: Mapped[float | None] = mapped_column(Float)
    recommendation: Mapped[str | None] = mapped_column(Text)
    geometry: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    attributes: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    source: Mapped[str | None] = mapped_column(String(128))
    reviewed: Mapped[bool] = mapped_column(Boolean, default=False, index=True)

    workspace: Mapped["Workspace"] = relationship(back_populates="findings")
    entity: Mapped["Entity | None"] = relationship(back_populates="findings")
    media: Mapped["Media | None"] = relationship(back_populates="findings")
    job: Mapped["ProcessingJob | None"] = relationship(back_populates="findings")
