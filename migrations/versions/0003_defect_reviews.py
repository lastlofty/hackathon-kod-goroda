"""Keep operator decisions separately from immutable survey results."""

import sqlalchemy as sa
from alembic import op

revision = "0003_defect_reviews"
down_revision = "0002_annotation_revisions"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "defect_reviews",
        sa.Column(
            "job_id",
            sa.Uuid(),
            sa.ForeignKey("processing_jobs.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("object_id", sa.String(512), primary_key=True),
        sa.Column("decision", sa.String(16), nullable=False),
        sa.Column("defect", sa.String(256)),
    )


def downgrade():
    op.drop_table("defect_reviews")
