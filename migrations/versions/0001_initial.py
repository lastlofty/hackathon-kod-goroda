"""Initial infrastructure monitoring schema."""

from alembic import op
import sqlalchemy as sa


revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "assets",
        sa.Column("external_id", sa.String(128), nullable=True),
        sa.Column("asset_type", sa.String(64), nullable=False),
        sa.Column("name", sa.String(255), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("latitude", sa.Float(), nullable=False),
        sa.Column("longitude", sa.Float(), nullable=False),
        sa.Column("address", sa.String(500), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_assets_asset_type", "assets", ["asset_type"])
    op.create_index("ix_assets_coordinates", "assets", ["latitude", "longitude"])
    op.create_index("ix_assets_external_id", "assets", ["external_id"], unique=True)
    op.create_index("ix_assets_latitude", "assets", ["latitude"])
    op.create_index("ix_assets_longitude", "assets", ["longitude"])

    op.create_table(
        "media",
        sa.Column("media_type", sa.String(16), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("original_filename", sa.String(500), nullable=True),
        sa.Column("content_type", sa.String(128), nullable=True),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("latitude", sa.Float(), nullable=True),
        sa.Column("longitude", sa.Float(), nullable=True),
        sa.Column("source", sa.String(128), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_media_captured_at", "media", ["captured_at"])

    op.create_table(
        "inspections",
        sa.Column("asset_id", sa.Uuid(), nullable=False),
        sa.Column("media_id", sa.Uuid(), nullable=True),
        sa.Column("observed_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("condition", sa.String(32), nullable=False),
        sa.Column("defect_type", sa.String(128), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("severity", sa.Integer(), nullable=False),
        sa.Column("recommendation", sa.Text(), nullable=True),
        sa.Column("bbox", sa.JSON(), nullable=True),
        sa.Column("model_name", sa.String(128), nullable=True),
        sa.Column("model_version", sa.String(64), nullable=True),
        sa.Column("reviewed", sa.Boolean(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("confidence >= 0 AND confidence <= 1", name="ck_inspection_confidence"),
        sa.CheckConstraint("severity >= 0 AND severity <= 100", name="ck_inspection_severity"),
        sa.ForeignKeyConstraint(["asset_id"], ["assets.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["media_id"], ["media.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_inspections_asset_id", "inspections", ["asset_id"])
    op.create_index("ix_inspections_asset_observed", "inspections", ["asset_id", "observed_at"])
    op.create_index("ix_inspections_condition", "inspections", ["condition"])
    op.create_index("ix_inspections_defect_type", "inspections", ["defect_type"])
    op.create_index("ix_inspections_media_id", "inspections", ["media_id"])
    op.create_index("ix_inspections_observed_at", "inspections", ["observed_at"])
    op.create_index("ix_inspections_reviewed", "inspections", ["reviewed"])


def downgrade() -> None:
    op.drop_table("inspections")
    op.drop_table("media")
    op.drop_table("assets")
