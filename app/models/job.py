from datetime import datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID

from sqlalchemy import JSON, DateTime, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.common import UUIDTimestampMixin

if TYPE_CHECKING:
    from app.models.finding import Finding
    from app.models.media import Media
    from app.models.workspace import Workspace


class ProcessingJob(UUIDTimestampMixin, Base):
    """A model, import, export or other asynchronous processing run."""

    __tablename__ = "processing_jobs"
    __table_args__ = (Index("ix_jobs_workspace_status", "workspace_id", "status"),)

    workspace_id: Mapped[UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    media_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("media.id", ondelete="SET NULL"), index=True
    )
    pipeline: Mapped[str] = mapped_column(String(128), index=True)
    status: Mapped[str] = mapped_column(String(32), default="queued", index=True)
    parameters: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    result: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    error_message: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    workspace: Mapped["Workspace"] = relationship(back_populates="jobs")
    media: Mapped["Media | None"] = relationship(back_populates="jobs")
    findings: Mapped[list["Finding"]] = relationship(back_populates="job")
