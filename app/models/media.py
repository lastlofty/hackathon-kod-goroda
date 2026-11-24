from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Float, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.common import UUIDTimestampMixin

if TYPE_CHECKING:
    from app.models.inspection import Inspection


class Media(UUIDTimestampMixin, Base):
    __tablename__ = "media"

    media_type: Mapped[str] = mapped_column(String(16), default="image")
    url: Mapped[str] = mapped_column(Text)
    original_filename: Mapped[str | None] = mapped_column(String(500))
    content_type: Mapped[str | None] = mapped_column(String(128))
    captured_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    latitude: Mapped[float | None] = mapped_column(Float)
    longitude: Mapped[float | None] = mapped_column(Float)
    source: Mapped[str | None] = mapped_column(String(128))

    inspections: Mapped[list["Inspection"]] = relationship(
        back_populates="media", cascade="all, delete-orphan"
    )
