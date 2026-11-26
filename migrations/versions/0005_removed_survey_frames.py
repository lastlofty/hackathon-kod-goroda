"""Remember which frames were removed from each survey."""

import sqlalchemy as sa
from alembic import op

revision = "0005_removed_survey_frames"
down_revision = "0004_cabinet_reviews"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "removed_survey_frames",
        sa.Column(
            "job_id",
            sa.Uuid(),
            sa.ForeignKey("processing_jobs.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("media_id", sa.Uuid(), primary_key=True),
    )


def downgrade():
    op.drop_table("removed_survey_frames")
