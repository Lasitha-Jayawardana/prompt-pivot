"""per-version notes; case-sensitive prompt names on MySQL

Revision ID: 0002
Revises: 0001
"""

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade(prefix: str = "promptpivot_") -> None:
    bind = op.get_bind()
    columns = {c["name"] for c in sa.inspect(bind).get_columns(f"{prefix}versions")}
    if "notes" not in columns:
        op.add_column(f"{prefix}versions", sa.Column("notes", sa.JSON(), nullable=True))
    if bind.dialect.name in ("mysql", "mariadb"):
        op.alter_column(
            f"{prefix}prompts",
            "name",
            type_=sa.String(255, collation="utf8mb4_bin"),
            existing_type=sa.String(255),
            existing_nullable=False,
        )


def downgrade(prefix: str = "promptpivot_") -> None:
    bind = op.get_bind()
    if bind.dialect.name in ("mysql", "mariadb"):
        op.alter_column(
            f"{prefix}prompts",
            "name",
            type_=sa.String(255),
            existing_type=sa.String(255, collation="utf8mb4_bin"),
            existing_nullable=False,
        )
    op.drop_column(f"{prefix}versions", "notes")
