"""Database operations. Every function takes a sync ``Connection`` inside a transaction.

The registry runs these directly on a sync engine, or through ``AsyncConnection.run_sync`` on
an async engine, so there is a single implementation of each rule.
"""

from __future__ import annotations

import difflib
import json
from collections.abc import Iterable, Sequence
from dataclasses import replace
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import Connection, CursorResult, Row, func, insert, select, update

from .errors import PromptConflict, PromptNotFound, PromptPolicyError, PromptValidationError
from .models import (
    AuditRecord,
    ChangeRequestRecord,
    LabelRecord,
    PromptRecord,
    VersionRecord,
)
from .schema import Tables
from .templating import checksum, detect_variables, normalize_template

CR_STATUSES = ("open", "approved", "rejected", "published")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _pk(res: CursorResult[Any]) -> int:
    pk = res.inserted_primary_key
    assert pk is not None
    return int(pk[0])


def locale_candidates(locale: str, default: str) -> tuple[str, ...]:
    """``pt-BR`` -> (``pt-BR``, ``pt``, ``en``). Exact, then base language, then default."""
    out = [locale]
    base = locale.split("-", 1)[0]
    if base != locale:
        out.append(base)
    if default not in out:
        out.append(default)
    return tuple(out)


class Store:
    def __init__(
        self,
        tables: Tables,
        *,
        default_locale: str,
        protected_labels: frozenset[str],
        require_distinct_approver: bool,
    ) -> None:
        self.t = tables
        self.default_locale = default_locale
        self.protected_labels = protected_labels
        self.require_distinct_approver = require_distinct_approver

    # -- helpers ---------------------------------------------------------------------------------

    def _audit(
        self,
        conn: Connection,
        actor: str,
        action: str,
        target_type: str,
        target_id: str,
        before: dict[str, Any] | None = None,
        after: dict[str, Any] | None = None,
        reason: str | None = None,
    ) -> None:
        conn.execute(
            insert(self.t.audit_log).values(
                at=_now(),
                actor=actor,
                action=action,
                target_type=target_type,
                target_id=target_id,
                before=before,
                after=after,
                reason=reason,
            )
        )

    def _prompt_row(self, conn: Connection, name: str) -> Row[Any]:
        row = conn.execute(select(self.t.prompts).where(self.t.prompts.c.name == name)).first()
        if row is None:
            raise PromptNotFound(f"prompt {name!r} does not exist")
        return row

    def _version_row(self, conn: Connection, prompt_id: int, locale: str, version: int) -> Row[Any]:
        v = self.t.versions
        row = conn.execute(
            select(v).where(v.c.prompt_id == prompt_id, v.c.locale == locale, v.c.version == version)
        ).first()
        if row is None:
            raise PromptNotFound(f"version {version} ({locale}) does not exist")
        return row

    @staticmethod
    def _prompt(row: Row[Any]) -> PromptRecord:
        return PromptRecord(
            row.id,
            row.name,
            row.type,
            row.description,
            tuple(row.tags or ()),
            dict(row.metadata or {}),
            row.archived_at,
            row.created_at,
            row.updated_at,
        )

    @staticmethod
    def _version(row: Row[Any]) -> VersionRecord:
        return VersionRecord(
            row.id,
            row.prompt_id,
            row.locale,
            row.version,
            row.format,
            row.template,
            dict(row.config or {}),
            tuple(row.variables or ()),
            row.checksum,
            row.message,
            row.created_by,
            row.created_at,
        )

    # -- read path -------------------------------------------------------------------------------

    def resolve(self, conn: Connection, name: str, label: str, locales: Sequence[str]) -> dict[str, Any]:
        """One indexed query: the labelled version for the first locale in ``locales`` that has it."""
        p, v, lb = self.t.prompts, self.t.versions, self.t.labels
        rows = (
            conn.execute(
                select(v, p.c.type.label("prompt_type"), p.c.metadata.label("prompt_metadata"))
                .select_from(lb)
                .join(p, p.c.id == lb.c.prompt_id)
                .join(v, v.c.id == lb.c.version_id)
                .where(p.c.name == name, lb.c.label == label, lb.c.locale.in_(locales), p.c.archived_at.is_(None))
            )
            .mappings()
            .all()
        )
        by_locale = {r["locale"]: r for r in rows}
        for loc in locales:
            if loc in by_locale:
                return dict(by_locale[loc])
        raise PromptNotFound(f"no version of {name!r} carries label {label!r} for {locales}")

    def health(self, conn: Connection) -> bool:
        conn.execute(select(1))
        return True

    # -- prompts ---------------------------------------------------------------------------------

    def create_prompt(
        self,
        conn: Connection,
        name: str,
        type: str,
        actor: str,
        description: str | None = None,
        tags: Iterable[str] = (),
        metadata: dict[str, Any] | None = None,
    ) -> PromptRecord:
        if type not in ("text", "chat"):
            raise PromptValidationError("type must be 'text' or 'chat'")
        if not name or name.startswith("/") or name.endswith("/") or "//" in name or " " in name:
            raise PromptValidationError("name must look like 'team/use-case/step'")
        if conn.execute(select(self.t.prompts.c.id).where(self.t.prompts.c.name == name)).first():
            raise PromptConflict(f"prompt {name!r} already exists")
        now = _now()
        after = {"name": name, "type": type, "description": description, "tags": list(tags), "metadata": metadata or {}}
        _pk(
            conn.execute(
                insert(self.t.prompts).values(
                    **after,
                    archived_at=None,
                    created_at=now,
                    updated_at=now,
                )
            )
        )
        self._audit(conn, actor, "create", "prompt", name, None, after)
        return self._prompt(self._prompt_row(conn, name))

    def get_prompt(self, conn: Connection, name: str) -> PromptRecord:
        return self._prompt(self._prompt_row(conn, name))

    def list_prompts(
        self,
        conn: Connection,
        *,
        q: str | None = None,
        tag: str | None = None,
        metadata: dict[str, Any] | None = None,
        include_archived: bool = False,
    ) -> list[PromptRecord]:
        p = self.t.prompts
        stmt = select(p).order_by(p.c.name)
        if q:
            stmt = stmt.where(p.c.name.like(f"%{q}%"))
        if not include_archived:
            stmt = stmt.where(p.c.archived_at.is_(None))
        out = [self._prompt(r) for r in conn.execute(stmt)]
        if tag:
            out = [r for r in out if tag in r.tags]
        if metadata:
            out = [r for r in out if all(r.metadata.get(k) == v for k, v in metadata.items())]
        return out

    def update_metadata(
        self,
        conn: Connection,
        name: str,
        metadata: dict[str, Any],
        actor: str,
    ) -> PromptRecord:
        row = self._prompt_row(conn, name)
        conn.execute(
            update(self.t.prompts).where(self.t.prompts.c.id == row.id).values(metadata=metadata, updated_at=_now())
        )
        self._audit(conn, actor, "metadata", "prompt", name, {"metadata": row.metadata}, {"metadata": metadata})
        return self._prompt(self._prompt_row(conn, name))

    def update_prompt(
        self,
        conn: Connection,
        name: str,
        actor: str,
        *,
        description: str | None = None,
        tags: Iterable[str] | None = None,
    ) -> PromptRecord:
        row = self._prompt_row(conn, name)
        values: dict[str, Any] = {"updated_at": _now()}
        if description is not None:
            values["description"] = description
        if tags is not None:
            values["tags"] = list(tags)
        conn.execute(update(self.t.prompts).where(self.t.prompts.c.id == row.id).values(**values))
        after = {k: v for k, v in values.items() if k != "updated_at"}
        self._audit(conn, actor, "update", "prompt", name, {"description": row.description, "tags": row.tags}, after)
        return self._prompt(self._prompt_row(conn, name))

    def archive(self, conn: Connection, name: str, actor: str, archived: bool = True) -> PromptRecord:
        row = self._prompt_row(conn, name)
        at = _now() if archived else None
        conn.execute(
            update(self.t.prompts).where(self.t.prompts.c.id == row.id).values(archived_at=at, updated_at=_now())
        )
        self._audit(conn, actor, "archive" if archived else "unarchive", "prompt", name)
        return self._prompt(self._prompt_row(conn, name))

    # -- versions --------------------------------------------------------------------------------

    def create_version(
        self,
        conn: Connection,
        name: str,
        template: Any,
        *,
        format: str,
        message: str,
        actor: str,
        locale: str | None = None,
        config: dict[str, Any] | None = None,
        variables: Sequence[str] | None = None,
    ) -> VersionRecord:
        """Save an immutable version and move ``latest``.

        ``config=None`` keeps the previous version's config for this locale; pass ``{}`` to clear it.
        ``record.warning`` is set when a locale variant's variables differ from the default locale's
        production version.
        """
        locale = locale or self.default_locale
        template = normalize_template(template)
        if format not in ("python", "jinja"):
            raise PromptValidationError("format must be 'python' or 'jinja'")
        p = self._prompt_row(conn, name)
        if p.type == "chat" and not isinstance(template, list):
            raise PromptValidationError("a chat prompt needs a list of messages")
        if p.type == "text" and not isinstance(template, str):
            raise PromptValidationError("a text prompt needs a string template")
        if config is None:
            prev = conn.execute(
                select(self.t.versions.c.config)
                .where(self.t.versions.c.prompt_id == p.id, self.t.versions.c.locale == locale)
                .order_by(self.t.versions.c.version.desc())
                .limit(1)
            ).scalar()
            config = dict(prev or {})
        vars_ = tuple(variables) if variables is not None else detect_variables(template, format)
        v = self.t.versions
        number = (
            conn.execute(
                select(func.coalesce(func.max(v.c.version), 0)).where(v.c.prompt_id == p.id, v.c.locale == locale)
            ).scalar_one()
            + 1
        )
        now = _now()
        vid = _pk(
            conn.execute(
                insert(v).values(
                    prompt_id=p.id,
                    locale=locale,
                    version=number,
                    format=format,
                    template=template,
                    config=config,
                    variables=list(vars_),
                    checksum=checksum(template, format, config),
                    message=message,
                    created_by=actor,
                    created_at=now,
                )
            )
        )
        conn.execute(update(self.t.prompts).where(self.t.prompts.c.id == p.id).values(updated_at=now))
        self._audit(
            conn,
            actor,
            "version",
            "prompt",
            name,
            None,
            {"locale": locale, "version": number, "format": format, "message": message},
        )
        self._move_label(conn, p.id, locale, "latest", vid, actor, None, None, None, audit=False)
        warning = None
        if locale != self.default_locale:
            prod = self._label_row(conn, p.id, self.default_locale, "production")
            if prod is not None:
                base = self._version_by_id(conn, prod.version_id)
                if set(base.variables or ()) != set(vars_):
                    warning = (
                        f"variables {sorted(vars_)} differ from the {self.default_locale} "
                        f"production version's {sorted(base.variables or ())}"
                    )
        rec = self._version(self._version_row(conn, p.id, locale, number))
        return replace(rec, warning=warning) if warning else rec

    def _version_by_id(self, conn: Connection, version_id: int) -> Row[Any]:
        row = conn.execute(select(self.t.versions).where(self.t.versions.c.id == version_id)).first()
        if row is None:
            raise PromptNotFound(f"version id {version_id} does not exist")
        return row

    def history(self, conn: Connection, name: str, locale: str | None = None) -> list[VersionRecord]:
        p = self._prompt_row(conn, name)
        v = self.t.versions
        stmt = select(v).where(v.c.prompt_id == p.id).order_by(v.c.locale, v.c.version.desc())
        if locale:
            stmt = stmt.where(v.c.locale == locale)
        return [self._version(r) for r in conn.execute(stmt)]

    def diff(self, conn: Connection, name: str, a: int, b: int, locale: str | None = None) -> str:
        """Unified diff of template, format and config between versions ``a`` and ``b``."""
        locale = locale or self.default_locale
        p = self._prompt_row(conn, name)
        va, vb = self._version_row(conn, p.id, locale, a), self._version_row(conn, p.id, locale, b)

        def dump(r: Row[Any]) -> list[str]:
            tpl = r.template if isinstance(r.template, str) else json.dumps(r.template, indent=2)
            cfg = json.dumps(r.config or {}, indent=2, sort_keys=True)
            return f"format: {r.format}\n--- template ---\n{tpl}\n--- config ---\n{cfg}\n".splitlines(True)

        return "".join(difflib.unified_diff(dump(va), dump(vb), f"v{a}", f"v{b}"))

    # -- labels ----------------------------------------------------------------------------------

    def _label_row(self, conn: Connection, prompt_id: int, locale: str, label: str) -> Row[Any] | None:
        lb = self.t.labels
        return conn.execute(
            select(lb).where(lb.c.prompt_id == prompt_id, lb.c.locale == locale, lb.c.label == label)
        ).first()

    def _move_label(
        self,
        conn: Connection,
        prompt_id: int,
        locale: str,
        label: str,
        to_version_id: int,
        actor: str,
        expected_current: int | None,
        reason: str | None,
        cr_id: int | None,
        *,
        audit: bool = True,
        action: str = "publish",
    ) -> LabelRecord:
        lb, now = self.t.labels, _now()
        row = self._label_row(conn, prompt_id, locale, label)
        from_id: int | None = None
        if row is None:
            if expected_current is not None:
                raise PromptConflict(f"label {label!r} is not set yet (expected v{expected_current})")
            label_id = _pk(
                conn.execute(
                    insert(lb).values(
                        prompt_id=prompt_id,
                        locale=locale,
                        label=label,
                        version_id=to_version_id,
                        updated_by=actor,
                        updated_at=now,
                        lock_version=0,
                    )
                )
            )
        else:
            current_id: int = row.version_id
            from_id = current_id
            if expected_current is not None:
                current = self._version_by_id(conn, current_id).version
                if current != expected_current:
                    raise PromptConflict(f"label {label!r} is at v{current}, expected v{expected_current}")
            res = conn.execute(
                update(lb)
                .where(lb.c.id == row.id, lb.c.lock_version == row.lock_version)
                .values(version_id=to_version_id, updated_by=actor, updated_at=now, lock_version=row.lock_version + 1)
            )
            if res.rowcount != 1:
                raise PromptConflict(f"label {label!r} was moved concurrently; retry")
            label_id = row.id
        conn.execute(
            insert(self.t.label_history).values(
                label_id=label_id,
                from_version_id=from_id,
                to_version_id=to_version_id,
                actor=actor,
                reason=reason,
                change_request_id=cr_id,
                at=now,
            )
        )
        if audit:
            name = conn.execute(select(self.t.prompts.c.name).where(self.t.prompts.c.id == prompt_id)).scalar_one()
            self._audit(
                conn,
                actor,
                action,
                "label",
                f"{name}:{locale}:{label}",
                {"version_id": from_id},
                {"version_id": to_version_id, "cr": cr_id},
                reason,
            )
        return self._label(conn, label_id)

    def _label(self, conn: Connection, label_id: int) -> LabelRecord:
        lb, v = self.t.labels, self.t.versions
        r = conn.execute(select(lb, v.c.version).join(v, v.c.id == lb.c.version_id).where(lb.c.id == label_id)).first()
        assert r is not None
        return LabelRecord(
            r.id, r.prompt_id, r.locale, r.label, r.version_id, r.version, r.updated_by, r.updated_at, r.lock_version
        )

    def labels(self, conn: Connection, name: str, locale: str | None = None) -> list[LabelRecord]:
        p = self._prompt_row(conn, name)
        lb, v = self.t.labels, self.t.versions
        stmt = (
            select(lb, v.c.version)
            .join(v, v.c.id == lb.c.version_id)
            .where(lb.c.prompt_id == p.id)
            .order_by(lb.c.locale, lb.c.label)
        )
        if locale:
            stmt = stmt.where(lb.c.locale == locale)
        return [
            LabelRecord(
                r.id,
                r.prompt_id,
                r.locale,
                r.label,
                r.version_id,
                r.version,
                r.updated_by,
                r.updated_at,
                r.lock_version,
            )
            for r in conn.execute(stmt)
        ]

    def labels_many(self, conn: Connection, names: Sequence[str]) -> dict[str, list[LabelRecord]]:
        """Labels for many prompts in one query (list page)."""
        if not names:
            return {}
        p, lb, v = self.t.prompts, self.t.labels, self.t.versions
        stmt = (
            select(lb, v.c.version, p.c.name)
            .join(v, v.c.id == lb.c.version_id)
            .join(p, p.c.id == lb.c.prompt_id)
            .where(p.c.name.in_(names))
            .order_by(lb.c.locale, lb.c.label)
        )
        out: dict[str, list[LabelRecord]] = {n: [] for n in names}
        for r in conn.execute(stmt):
            out[r.name].append(
                LabelRecord(
                    r.id,
                    r.prompt_id,
                    r.locale,
                    r.label,
                    r.version_id,
                    r.version,
                    r.updated_by,
                    r.updated_at,
                    r.lock_version,
                )
            )
        return out

    def publish(
        self,
        conn: Connection,
        name: str,
        version: int,
        label: str,
        *,
        actor: str,
        locale: str | None = None,
        expected_current: int | None = None,
        reason: str | None = None,
        force: bool = False,
    ) -> LabelRecord:
        """Move ``label`` to ``version``. Protected labels need an approved change request."""
        locale = locale or self.default_locale
        if label == "latest":
            raise PromptPolicyError("'latest' moves automatically on save")
        p = self._prompt_row(conn, name)
        v = self._version_row(conn, p.id, locale, version)
        cr_id: int | None = None
        if label in self.protected_labels and not force:
            cr = self.t.change_requests
            row = conn.execute(
                select(cr)
                .where(
                    cr.c.prompt_id == p.id,
                    cr.c.locale == locale,
                    cr.c.version_id == v.id,
                    cr.c.target_label == label,
                    cr.c.status == "approved",
                )
                .order_by(cr.c.id.desc())
            ).first()
            if row is None:
                raise PromptPolicyError(f"label {label!r} is protected: request a change and get it approved first")
            cr_id = row.id
            conn.execute(update(cr).where(cr.c.id == cr_id).values(status="published"))
        if force:
            reason = f"break-glass: {reason or 'no reason given'}"
        return self._move_label(conn, p.id, locale, label, v.id, actor, expected_current, reason, cr_id)

    def rollback(
        self,
        conn: Connection,
        name: str,
        label: str,
        *,
        actor: str,
        locale: str | None = None,
        reason: str | None = None,
    ) -> LabelRecord:
        """Move ``label`` back to the version it pointed to before its last move.

        This undoes the last move, so calling it twice re-applies that move. Use
        :meth:`rollback_target` to show the destination before acting.
        """
        locale = locale or self.default_locale
        p = self._prompt_row(conn, name)
        row = self._label_row(conn, p.id, locale, label)
        if row is None:
            raise PromptNotFound(f"label {label!r} is not set for {name!r} ({locale})")
        h = self.t.label_history
        last = conn.execute(
            select(h).where(h.c.label_id == row.id, h.c.to_version_id == row.version_id).order_by(h.c.id.desc())
        ).first()
        if last is None or last.from_version_id is None:
            raise PromptNotFound(f"label {label!r} has no previous version to roll back to")
        return self._move_label(
            conn, p.id, locale, label, last.from_version_id, actor, None, reason or "rollback", None, action="rollback"
        )

    def rollback_target(self, conn: Connection, name: str, label: str, locale: str | None = None) -> int | None:
        """Version number ``rollback`` would move ``label`` to, or None when there is none."""
        locale = locale or self.default_locale
        p = self._prompt_row(conn, name)
        row = self._label_row(conn, p.id, locale, label)
        if row is None:
            return None
        h = self.t.label_history
        last = conn.execute(
            select(h.c.from_version_id)
            .where(h.c.label_id == row.id, h.c.to_version_id == row.version_id)
            .order_by(h.c.id.desc())
        ).scalar()
        return int(self._version_by_id(conn, last).version) if last else None

    def label_history(
        self,
        conn: Connection,
        name: str,
        label: str,
        locale: str | None = None,
    ) -> list[dict[str, Any]]:
        locale = locale or self.default_locale
        p = self._prompt_row(conn, name)
        row = self._label_row(conn, p.id, locale, label)
        if row is None:
            return []
        h = self.t.label_history
        return [
            dict(r) for r in conn.execute(select(h).where(h.c.label_id == row.id).order_by(h.c.id.desc())).mappings()
        ]

    # -- change requests -------------------------------------------------------------------------

    def _cr(self, conn: Connection, cr_id: int) -> ChangeRequestRecord:
        cr, p, v = self.t.change_requests, self.t.prompts, self.t.versions
        r = conn.execute(
            select(cr, p.c.name, v.c.version)
            .join(p, p.c.id == cr.c.prompt_id)
            .join(v, v.c.id == cr.c.version_id)
            .where(cr.c.id == cr_id)
        ).first()
        if r is None:
            raise PromptNotFound(f"change request {cr_id} does not exist")
        return ChangeRequestRecord(
            r.id,
            r.prompt_id,
            r.name,
            r.locale,
            r.version_id,
            r.version,
            r.target_label,
            r.status,
            r.author,
            r.reviewer,
            r.comment,
            r.created_at,
            r.decided_at,
        )

    def request_change(
        self,
        conn: Connection,
        name: str,
        version: int,
        label: str,
        *,
        actor: str,
        locale: str | None = None,
        comment: str | None = None,
    ) -> ChangeRequestRecord:
        locale = locale or self.default_locale
        p = self._prompt_row(conn, name)
        v = self._version_row(conn, p.id, locale, version)
        cr_id = _pk(
            conn.execute(
                insert(self.t.change_requests).values(
                    prompt_id=p.id,
                    locale=locale,
                    version_id=v.id,
                    target_label=label,
                    status="open",
                    author=actor,
                    comment=comment,
                    created_at=_now(),
                )
            )
        )
        self._audit(
            conn,
            actor,
            "request",
            "change_request",
            str(cr_id),
            None,
            {"prompt": name, "locale": locale, "version": version, "label": label},
        )
        return self._cr(conn, cr_id)

    def _decide(
        self, conn: Connection, cr_id: int, actor: str, status: str, comment: str | None
    ) -> ChangeRequestRecord:
        rec = self._cr(conn, cr_id)
        if rec.status != "open":
            raise PromptPolicyError(f"change request {cr_id} is already {rec.status}")
        if status == "approved" and self.require_distinct_approver and actor == rec.author:
            raise PromptPolicyError("the approver must differ from the author")
        cr = self.t.change_requests
        values: dict[str, Any] = {"status": status, "reviewer": actor, "decided_at": _now()}
        if comment:
            values["comment"] = comment
        conn.execute(update(cr).where(cr.c.id == cr_id).values(**values))
        self._audit(
            conn,
            actor,
            status[:-1] if status.endswith("d") else status,
            "change_request",
            str(cr_id),
            {"status": "open"},
            {"status": status},
            comment,
        )
        return self._cr(conn, cr_id)

    def approve(self, conn: Connection, cr_id: int, actor: str, comment: str | None = None) -> ChangeRequestRecord:
        return self._decide(conn, cr_id, actor, "approved", comment)

    def reject(self, conn: Connection, cr_id: int, actor: str, comment: str | None = None) -> ChangeRequestRecord:
        return self._decide(conn, cr_id, actor, "rejected", comment)

    def list_change_requests(
        self,
        conn: Connection,
        name: str | None = None,
        status: str | None = None,
    ) -> list[ChangeRequestRecord]:
        cr, p, v = self.t.change_requests, self.t.prompts, self.t.versions
        stmt = (
            select(cr, p.c.name, v.c.version)
            .join(p, p.c.id == cr.c.prompt_id)
            .join(v, v.c.id == cr.c.version_id)
            .order_by(cr.c.id.desc())
        )
        if name:
            stmt = stmt.where(p.c.name == name)
        if status:
            stmt = stmt.where(cr.c.status == status)
        return [
            ChangeRequestRecord(
                r.id,
                r.prompt_id,
                r.name,
                r.locale,
                r.version_id,
                r.version,
                r.target_label,
                r.status,
                r.author,
                r.reviewer,
                r.comment,
                r.created_at,
                r.decided_at,
            )
            for r in conn.execute(stmt)
        ]

    # -- audit -----------------------------------------------------------------------------------

    def audit(
        self,
        conn: Connection,
        *,
        target_type: str | None = None,
        target_id: str | None = None,
        actor: str | None = None,
        limit: int = 200,
    ) -> list[AuditRecord]:
        a = self.t.audit_log
        stmt = select(a).order_by(a.c.id.desc()).limit(limit)
        if target_type:
            stmt = stmt.where(a.c.target_type == target_type)
        if target_id:
            stmt = stmt.where(a.c.target_id.like(f"{target_id}%"))
        if actor:
            stmt = stmt.where(a.c.actor == actor)
        return [
            AuditRecord(r.id, r.at, r.actor, r.action, r.target_type, r.target_id, r.before, r.after, r.reason)
            for r in conn.execute(stmt)
        ]

    # -- portability -----------------------------------------------------------------------------

    def export_all(self, conn: Connection, names: Sequence[str] | None = None) -> dict[str, Any]:
        """Prompts, versions and labels as plain data (JSON/YAML friendly)."""
        out: list[dict[str, Any]] = []
        for pr in self.list_prompts(conn, include_archived=True):
            if names and pr.name not in names:
                continue
            locales: dict[str, Any] = {}
            for v in sorted(self.history(conn, pr.name), key=lambda r: (r.locale, r.version)):
                loc = locales.setdefault(v.locale, {"versions": [], "labels": {}})
                loc["versions"].append(
                    {
                        "version": v.version,
                        "format": v.format,
                        "template": v.template,
                        "config": v.config,
                        "variables": list(v.variables),
                        "message": v.message,
                        "created_by": v.created_by,
                        "created_at": v.created_at.isoformat(),
                    }
                )
            for lb in self.labels(conn, pr.name):
                if lb.label != "latest":
                    locales.setdefault(lb.locale, {"versions": [], "labels": {}})["labels"][lb.label] = lb.version
            out.append(
                {
                    "name": pr.name,
                    "type": pr.type,
                    "description": pr.description,
                    "tags": list(pr.tags),
                    "metadata": pr.metadata,
                    "locales": locales,
                }
            )
        return {"promptpivot": 1, "prompts": out}

    def import_all(
        self, conn: Connection, data: dict[str, Any], actor: str, *, set_labels: bool = True
    ) -> dict[str, int]:
        """Create missing prompts and versions (matched by checksum); optionally set labels."""
        counts = {"prompts": 0, "versions": 0, "labels": 0}
        for item in data.get("prompts", []):
            name = item["name"]
            try:
                self._prompt_row(conn, name)
            except PromptNotFound:
                self.create_prompt(
                    conn,
                    name,
                    item.get("type", "text"),
                    actor,
                    item.get("description"),
                    item.get("tags", ()),
                    item.get("metadata"),
                )
                counts["prompts"] += 1
            for locale, loc in item.get("locales", {}).items():
                existing = {v.checksum: v.version for v in self.history(conn, name, locale)}
                mapping: dict[int, int] = {}
                for v in loc.get("versions", []):
                    cs = checksum(v["template"], v["format"], v.get("config") or {})
                    if cs in existing:
                        mapping[v["version"]] = existing[cs]
                        continue
                    rec = self.create_version(
                        conn,
                        name,
                        v["template"],
                        format=v["format"],
                        message=v.get("message", "imported"),
                        actor=v.get("created_by", actor),
                        locale=locale,
                        config=v.get("config") or {},
                        variables=v.get("variables"),
                    )
                    existing[cs] = mapping[v["version"]] = rec.version
                    counts["versions"] += 1
                if set_labels:
                    for label, ver in loc.get("labels", {}).items():
                        target = mapping[ver] if ver in mapping else int(ver)
                        current = self._label_row(conn, self._prompt_row(conn, name).id, locale, label)
                        if current is not None and self._version_by_id(conn, current.version_id).version == target:
                            continue
                        self.publish(conn, name, target, label, actor=actor, locale=locale, reason="import", force=True)
                        counts["labels"] += 1
        return counts
