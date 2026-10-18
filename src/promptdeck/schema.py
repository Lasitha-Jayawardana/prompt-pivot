"""SQLAlchemy Core tables. Portable types only; identical on PostgreSQL, MySQL and SQLite."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import (
    JSON,
    BigInteger,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    UniqueConstraint,
)

DEFAULT_PREFIX = "promptdeck_"
BigId = BigInteger().with_variant(Integer(), "sqlite")


@dataclass(frozen=True)
class Tables:
    metadata: MetaData
    prompts: Table
    versions: Table
    labels: Table
    label_history: Table
    change_requests: Table
    audit_log: Table


def build_tables(prefix: str = DEFAULT_PREFIX) -> Tables:
    """Build the six tables with ``prefix``. Call once per registry."""
    md = MetaData()
    p = prefix

    prompts = Table(
        f"{p}prompts",
        md,
        Column("id", BigId, primary_key=True, autoincrement=True),
        Column("name", String(255), nullable=False, unique=True),
        Column("type", String(8), nullable=False),
        Column("description", Text),
        Column("tags", JSON, nullable=False),
        Column("metadata", JSON, nullable=False),
        Column("archived_at", DateTime(timezone=True)),
        Column("created_at", DateTime(timezone=True), nullable=False),
        Column("updated_at", DateTime(timezone=True), nullable=False),
    )
    versions = Table(
        f"{p}versions",
        md,
        Column("id", BigId, primary_key=True, autoincrement=True),
        Column("prompt_id", BigId, ForeignKey(prompts.c.id), nullable=False),
        Column("locale", String(16), nullable=False),
        Column("version", Integer, nullable=False),
        Column("format", String(8), nullable=False),
        Column("template", JSON, nullable=False),
        Column("config", JSON, nullable=False),
        Column("variables", JSON, nullable=False),
        Column("checksum", String(32), nullable=False),
        Column("message", Text, nullable=False),
        Column("created_by", String(255), nullable=False),
        Column("created_at", DateTime(timezone=True), nullable=False),
        UniqueConstraint("prompt_id", "locale", "version", name=f"uq_{p}versions"),
    )
    labels = Table(
        f"{p}labels",
        md,
        Column("id", BigId, primary_key=True, autoincrement=True),
        Column("prompt_id", BigId, ForeignKey(prompts.c.id), nullable=False),
        Column("locale", String(16), nullable=False),
        Column("label", String(64), nullable=False),
        Column("version_id", BigId, ForeignKey(versions.c.id), nullable=False),
        Column("updated_by", String(255), nullable=False),
        Column("updated_at", DateTime(timezone=True), nullable=False),
        Column("lock_version", Integer, nullable=False, default=0),
        UniqueConstraint("prompt_id", "label", "locale", name=f"uq_{p}labels"),
    )
    label_history = Table(
        f"{p}label_history",
        md,
        Column("id", BigId, primary_key=True, autoincrement=True),
        Column("label_id", BigId, ForeignKey(labels.c.id), nullable=False),
        Column("from_version_id", BigId),
        Column("to_version_id", BigId, nullable=False),
        Column("actor", String(255), nullable=False),
        Column("reason", Text),
        Column("change_request_id", BigId),
        Column("at", DateTime(timezone=True), nullable=False),
        Index(f"ix_{p}label_history_label", "label_id", "id"),
    )
    change_requests = Table(
        f"{p}change_requests",
        md,
        Column("id", BigId, primary_key=True, autoincrement=True),
        Column("prompt_id", BigId, ForeignKey(prompts.c.id), nullable=False),
        Column("locale", String(16), nullable=False),
        Column("version_id", BigId, ForeignKey(versions.c.id), nullable=False),
        Column("target_label", String(64), nullable=False),
        Column("status", String(16), nullable=False),
        Column("author", String(255), nullable=False),
        Column("reviewer", String(255)),
        Column("comment", Text),
        Column("created_at", DateTime(timezone=True), nullable=False),
        Column("decided_at", DateTime(timezone=True)),
        Index(f"ix_{p}change_requests_prompt", "prompt_id", "status"),
    )
    audit_log = Table(
        f"{p}audit_log",
        md,
        Column("id", BigId, primary_key=True, autoincrement=True),
        Column("at", DateTime(timezone=True), nullable=False),
        Column("actor", String(255), nullable=False),
        Column("action", String(32), nullable=False),
        Column("target_type", String(32), nullable=False),
        Column("target_id", String(255), nullable=False),
        Column("before", JSON),
        Column("after", JSON),
        Column("reason", Text),
        Index(f"ix_{p}audit_log_target", "target_type", "target_id", "id"),
    )
    return Tables(md, prompts, versions, labels, label_history, change_requests, audit_log)
