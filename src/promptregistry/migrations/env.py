"""Alembic environment: always driven programmatically with an existing connection."""

from alembic import context

config = context.config
connection = config.attributes["connection"]
prefix = config.attributes.get("prefix", "promptregistry_")
context.configure(
    connection=connection,
    target_metadata=None,
    version_table=config.get_main_option("version_table") or f"{prefix}alembic_version",
)
with context.begin_transaction():
    context.run_migrations(prefix=prefix)
