from datetime import datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID

from sqlalchemy import JSON, DateTime, Float, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.common import UUIDTimestampMixin

if TYPE_CHECKING:
    from app.models.finding import Finding
    from app.models.job import ProcessingJob
    from app.models.workspace import Workspace


class Media(UUIDTimestampMixin, Base):
    __tablename__ = "media"

    workspace_id: Mapped[UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[str] = mapped_column(String(64), default="image", index=True)
    url: Mapped[str] = mapped_column(Text)
    original_filename: Mapped[str | None] = mapped_column(String(500))
    content_type: Mapped[str | None] = mapped_column(String(128))
    captured_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), index=True
    )
    latitude: Mapped[float | None] = mapped_column(Float)
    longitude: Mapped[float | None] = mapped_column(Float)
    source: Mapped[str | None] = mapped_column(String(128))
    attributes: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    workspace: Mapped["Workspace"] = relationship(back_populates="media")
    jobs: Mapped[list["ProcessingJob"]] = relationship(back_populates="media")
    findings: Mapped[list["Finding"]] = relationship(back_populates="media")
