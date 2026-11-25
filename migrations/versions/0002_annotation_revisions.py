"""Keep operator annotations separately from inference."""
import sqlalchemy as sa
from alembic import op

revision = "0002_annotation_revisions"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "annotation_revisions",
        sa.Column("media_id", sa.Uuid(), sa.ForeignKey("media.id", ondelete="CASCADE"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("author", sa.String(128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("overrides", sa.JSON(), nullable=False),
        sa.Column("changed_ids", sa.JSON(), nullable=False),
        sa.PrimaryKeyConstraint("media_id", "version"),
    )


def downgrade() -> None:
    op.drop_table("annotation_revisions")
