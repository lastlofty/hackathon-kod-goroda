"""Store multiple reviewed defects and operator-entered cabinet positions."""

import sqlalchemy as sa
from alembic import op

revision = "0004_cabinet_reviews"
down_revision = "0003_defect_reviews"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "defect_reviews",
        sa.Column("defects", sa.JSON(), nullable=False, server_default="[]"),
    )
    reviews = sa.table(
        "defect_reviews",
        sa.column("defect", sa.String()),
        sa.column("defects", sa.JSON()),
    )
    conn = op.get_bind()
    for defect in conn.execute(sa.select(reviews.c.defect).distinct()).scalars().all():
        if defect:
            conn.execute(
                reviews.update()
                .where(reviews.c.defect == defect)
                .values(defects=[defect])
            )
    with op.batch_alter_table("defect_reviews") as batch:
        batch.drop_column("defect")
    op.create_table(
        "survey_object_locations",
        sa.Column(
            "job_id",
            sa.Uuid(),
            sa.ForeignKey("processing_jobs.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("object_id", sa.String(512), primary_key=True),
        sa.Column("lat", sa.Float(), nullable=False),
        sa.Column("lon", sa.Float(), nullable=False),
    )


def downgrade():
    conn = op.get_bind()
    reviews = sa.table(
        "defect_reviews",
        sa.column("job_id", sa.Uuid()),
        sa.column("object_id"),
        sa.column("defect", sa.String()),
        sa.column("defects", sa.JSON()),
    )
    rows = conn.execute(
        sa.select(reviews.c.job_id, reviews.c.object_id, reviews.c.defects)
    ).all()
    if any(len(values) > 1 for _, _, values in rows):
        raise ValueError("В старом формате невозможно сохранить несколько дефектов")
    op.add_column("defect_reviews", sa.Column("defect", sa.String(256)))
    for job, obj, values in rows:
        if values:
            conn.execute(
                reviews.update()
                .where(reviews.c.job_id == job, reviews.c.object_id == obj)
                .values(defect=values[0])
            )
    with op.batch_alter_table("defect_reviews") as batch:
        batch.drop_column("defects")
    op.drop_table("survey_object_locations")
