"""Initial case-agnostic backend schema."""

import sqlalchemy as sa
from alembic import op

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def timestamps() -> list[sa.Column]:
    return [
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    ]


def upgrade() -> None:
    op.create_table(
        "workspaces",
        sa.Column("slug", sa.String(64), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("settings", sa.JSON(), nullable=False),
        *timestamps(),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_workspaces_slug", "workspaces", ["slug"], unique=True)

    op.create_table(
        "entity_types",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("code", sa.String(64), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("attribute_schema", sa.JSON(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        *timestamps(),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("workspace_id", "code", name="uq_entity_type_code"),
    )
    op.create_index("ix_entity_types_active", "entity_types", ["active"])
    op.create_index("ix_entity_types_workspace_id", "entity_types", ["workspace_id"])

    op.create_table(
        "entities",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("entity_type_id", sa.Uuid(), nullable=True),
        sa.Column("external_id", sa.String(128), nullable=True),
        sa.Column("name", sa.String(255), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("attributes", sa.JSON(), nullable=False),
        sa.Column("geometry", sa.JSON(), nullable=True),
        sa.Column("latitude", sa.Float(), nullable=True),
        sa.Column("longitude", sa.Float(), nullable=True),
        *timestamps(),
        sa.ForeignKeyConstraint(
            ["entity_type_id"], ["entity_types.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "workspace_id", "external_id", name="uq_entity_external_id"
        ),
    )
    op.create_index("ix_entities_coordinates", "entities", ["latitude", "longitude"])
    op.create_index("ix_entities_entity_type_id", "entities", ["entity_type_id"])
    op.create_index("ix_entities_latitude", "entities", ["latitude"])
    op.create_index("ix_entities_longitude", "entities", ["longitude"])
    op.create_index("ix_entities_workspace_id", "entities", ["workspace_id"])

    op.create_table(
        "media",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(64), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("original_filename", sa.String(500), nullable=True),
        sa.Column("content_type", sa.String(128), nullable=True),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("latitude", sa.Float(), nullable=True),
        sa.Column("longitude", sa.Float(), nullable=True),
        sa.Column("source", sa.String(128), nullable=True),
        sa.Column("attributes", sa.JSON(), nullable=False),
        *timestamps(),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_media_captured_at", "media", ["captured_at"])
    op.create_index("ix_media_kind", "media", ["kind"])
    op.create_index("ix_media_workspace_id", "media", ["workspace_id"])

    op.create_table(
        "processing_jobs",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("media_id", sa.Uuid(), nullable=True),
        sa.Column("pipeline", sa.String(128), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("parameters", sa.JSON(), nullable=False),
        sa.Column("result", sa.JSON(), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        *timestamps(),
        sa.ForeignKeyConstraint(["media_id"], ["media.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_jobs_workspace_status", "processing_jobs", ["workspace_id", "status"]
    )
    op.create_index("ix_processing_jobs_media_id", "processing_jobs", ["media_id"])
    op.create_index("ix_processing_jobs_pipeline", "processing_jobs", ["pipeline"])
    op.create_index("ix_processing_jobs_status", "processing_jobs", ["status"])
    op.create_index(
        "ix_processing_jobs_workspace_id", "processing_jobs", ["workspace_id"]
    )

    op.create_table(
        "findings",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("entity_id", sa.Uuid(), nullable=True),
        sa.Column("media_id", sa.Uuid(), nullable=True),
        sa.Column("job_id", sa.Uuid(), nullable=True),
        sa.Column(
            "observed_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("category", sa.String(128), nullable=False),
        sa.Column("label", sa.String(255), nullable=True),
        sa.Column("status", sa.String(64), nullable=True),
        sa.Column("score", sa.Float(), nullable=True),
        sa.Column("severity", sa.Float(), nullable=True),
        sa.Column("recommendation", sa.Text(), nullable=True),
        sa.Column("geometry", sa.JSON(), nullable=True),
        sa.Column("attributes", sa.JSON(), nullable=False),
        sa.Column("source", sa.String(128), nullable=True),
        sa.Column("reviewed", sa.Boolean(), nullable=False),
        *timestamps(),
        sa.CheckConstraint(
            "score IS NULL OR (score >= 0 AND score <= 1)", name="ck_finding_score"
        ),
        sa.ForeignKeyConstraint(["entity_id"], ["entities.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["job_id"], ["processing_jobs.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["media_id"], ["media.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_findings_category", "findings", ["category"])
    op.create_index("ix_findings_entity_id", "findings", ["entity_id"])
    op.create_index(
        "ix_findings_entity_observed", "findings", ["entity_id", "observed_at"]
    )
    op.create_index("ix_findings_job_id", "findings", ["job_id"])
    op.create_index("ix_findings_label", "findings", ["label"])
    op.create_index("ix_findings_media_id", "findings", ["media_id"])
    op.create_index("ix_findings_observed_at", "findings", ["observed_at"])
    op.create_index("ix_findings_reviewed", "findings", ["reviewed"])
    op.create_index("ix_findings_status", "findings", ["status"])
    op.create_index("ix_findings_workspace_id", "findings", ["workspace_id"])
    op.create_index(
        "ix_findings_workspace_status", "findings", ["workspace_id", "status"]
    )


def downgrade() -> None:
    op.drop_table("findings")
    op.drop_table("processing_jobs")
    op.drop_table("media")
    op.drop_table("entities")
    op.drop_table("entity_types")
    op.drop_table("workspaces")
