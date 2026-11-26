from uuid import UUID

from sqlalchemy import JSON, Float, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class DefectReview(Base):
    __tablename__ = "defect_reviews"

    job_id: Mapped[UUID] = mapped_column(
        ForeignKey("processing_jobs.id", ondelete="CASCADE"), primary_key=True
    )
    object_id: Mapped[str] = mapped_column(String(512), primary_key=True)
    decision: Mapped[str] = mapped_column(String(16))
    defects: Mapped[list[str]] = mapped_column(JSON, default=list)


class SurveyObjectLocation(Base):
    __tablename__ = "survey_object_locations"

    job_id: Mapped[UUID] = mapped_column(
        ForeignKey("processing_jobs.id", ondelete="CASCADE"), primary_key=True
    )
    object_id: Mapped[str] = mapped_column(String(512), primary_key=True)
    lat: Mapped[float] = mapped_column(Float)
    lon: Mapped[float] = mapped_column(Float)


class RemovedSurveyFrame(Base):
    __tablename__ = "removed_survey_frames"

    job_id: Mapped[UUID] = mapped_column(
        ForeignKey("processing_jobs.id", ondelete="CASCADE"), primary_key=True
    )
    media_id: Mapped[UUID] = mapped_column(primary_key=True)
