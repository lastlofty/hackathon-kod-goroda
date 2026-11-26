from uuid import UUID

from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class DefectReview(Base):
    __tablename__ = "defect_reviews"

    job_id: Mapped[UUID] = mapped_column(
        ForeignKey("processing_jobs.id", ondelete="CASCADE"), primary_key=True
    )
    object_id: Mapped[str] = mapped_column(String(512), primary_key=True)
    decision: Mapped[str] = mapped_column(String(16))
    defect: Mapped[str | None] = mapped_column(String(256))
