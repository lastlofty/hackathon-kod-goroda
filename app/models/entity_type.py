from typing import TYPE_CHECKING, Any
from uuid import UUID

from sqlalchemy import JSON, Boolean, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.common import UUIDTimestampMixin

if TYPE_CHECKING:
    from app.models.entity import Entity
    from app.models.workspace import Workspace


class EntityType(UUIDTimestampMixin, Base):
    """A case-specific object type with a UI/validation schema."""

    __tablename__ = "entity_types"
    __table_args__ = (
        UniqueConstraint("workspace_id", "code", name="uq_entity_type_code"),
    )

    workspace_id: Mapped[UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    code: Mapped[str] = mapped_column(String(64))
    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text)
    attribute_schema: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)

    workspace: Mapped["Workspace"] = relationship(back_populates="entity_types")
    entities: Mapped[list["Entity"]] = relationship(back_populates="entity_type")
