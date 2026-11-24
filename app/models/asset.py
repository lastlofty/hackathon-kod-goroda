from typing import TYPE_CHECKING

from sqlalchemy import Float, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.common import UUIDTimestampMixin

if TYPE_CHECKING:
    from app.models.inspection import Inspection


class Asset(UUIDTimestampMixin, Base):
    __tablename__ = "assets"
    __table_args__ = (Index("ix_assets_coordinates", "latitude", "longitude"),)

    external_id: Mapped[str | None] = mapped_column(String(128), unique=True, index=True)
    asset_type: Mapped[str] = mapped_column(String(64), index=True)
    name: Mapped[str | None] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text)
    latitude: Mapped[float] = mapped_column(Float, index=True)
    longitude: Mapped[float] = mapped_column(Float, index=True)
    address: Mapped[str | None] = mapped_column(String(500))

    inspections: Mapped[list["Inspection"]] = relationship(
        back_populates="asset", cascade="all, delete-orphan"
    )
