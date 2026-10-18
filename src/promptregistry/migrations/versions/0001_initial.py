"""initial schema: prompts, versions, labels, label_history, change_requests, audit_log

Revision ID: 0001
Revises:
"""

from alembic import op

from promptregistry.schema import build_tables

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade(prefix: str = "promptregistry_") -> None:
    build_tables(prefix).metadata.create_all(op.get_bind())


def downgrade(prefix: str = "promptregistry_") -> None:
    build_tables(prefix).metadata.drop_all(op.get_bind())
