from typing import TYPE_CHECKING, Any
from uuid import UUID

from sqlalchemy import JSON, Float, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.common import UUIDTimestampMixin

if TYPE_CHECKING:
    from app.models.entity_type import EntityType
    from app.models.finding import Finding
    from app.models.workspace import Workspace


class Entity(UUIDTimestampMixin, Base):
    """A generic domain object: equipment, animal, document, event, etc."""

    __tablename__ = "entities"
    __table_args__ = (
        UniqueConstraint("workspace_id", "external_id", name="uq_entity_external_id"),
        Index("ix_entities_coordinates", "latitude", "longitude"),
    )

    workspace_id: Mapped[UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    entity_type_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("entity_types.id", ondelete="SET NULL"), index=True
    )
    external_id: Mapped[str | None] = mapped_column(String(128))
    name: Mapped[str | None] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text)
    attributes: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    geometry: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    latitude: Mapped[float | None] = mapped_column(Float, index=True)
    longitude: Mapped[float | None] = mapped_column(Float, index=True)

    workspace: Mapped["Workspace"] = relationship(back_populates="entities")
    entity_type: Mapped["EntityType | None"] = relationship(back_populates="entities")
    findings: Mapped[list["Finding"]] = relationship(back_populates="entity")
