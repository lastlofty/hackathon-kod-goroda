from typing import TYPE_CHECKING, Any

from sqlalchemy import JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.common import UUIDTimestampMixin

if TYPE_CHECKING:
    from app.models.entity import Entity
    from app.models.entity_type import EntityType
    from app.models.finding import Finding
    from app.models.job import ProcessingJob
    from app.models.media import Media


class Workspace(UUIDTimestampMixin, Base):
    """An isolated case/TZ configuration and its data."""

    __tablename__ = "workspaces"

    slug: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text)
    settings: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    entity_types: Mapped[list["EntityType"]] = relationship(
        back_populates="workspace", cascade="all, delete-orphan"
    )
    entities: Mapped[list["Entity"]] = relationship(
        back_populates="workspace", cascade="all, delete-orphan"
    )
    media: Mapped[list["Media"]] = relationship(
        back_populates="workspace", cascade="all, delete-orphan"
    )
    jobs: Mapped[list["ProcessingJob"]] = relationship(
        back_populates="workspace", cascade="all, delete-orphan"
    )
    findings: Mapped[list["Finding"]] = relationship(
        back_populates="workspace", cascade="all, delete-orphan"
    )
