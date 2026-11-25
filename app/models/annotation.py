from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import JSON, DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class AnnotationRevision(Base):
    __tablename__ = "annotation_revisions"

    media_id: Mapped[UUID] = mapped_column(ForeignKey("media.id", ondelete="CASCADE"), primary_key=True)
    version: Mapped[int] = mapped_column(primary_key=True)
    author: Mapped[str] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    overrides: Mapped[dict[str, Any]] = mapped_column(JSON)
    changed_ids: Mapped[list[str]] = mapped_column(JSON)
