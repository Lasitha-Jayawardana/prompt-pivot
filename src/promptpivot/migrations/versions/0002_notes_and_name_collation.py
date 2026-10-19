"""per-version notes; case-sensitive names and microsecond timestamps on MySQL

Revision ID: 0002
Revises: 0001
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.mysql import DATETIME

TIMESTAMPS = {
    "prompts": ("archived_at", "created_at", "updated_at"),
    "versions": ("created_at",),
    "labels": ("updated_at",),
    "label_history": ("at",),
    "change_requests": ("created_at", "decided_at"),
    "audit_log": ("at",),
}
NULLABLE = {("prompts", "archived_at"), ("change_requests", "decided_at")}

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
        for table, cols in TIMESTAMPS.items():
            for col in cols:
                op.alter_column(
                    f"{prefix}{table}",
                    col,
                    type_=DATETIME(fsp=6),
                    existing_type=sa.DateTime(),
                    existing_nullable=(table, col) in NULLABLE,
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
