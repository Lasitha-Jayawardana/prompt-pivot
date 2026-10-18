"""``PromptRegistry``: the one object a host app creates."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import replace
from typing import Any, Generic, TypeVar, cast

from pydantic import BaseModel, ValidationError
from sqlalchemy import Connection, Engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine

from .cache import PromptCache
from .errors import (
    PromptDeckError,
    PromptNotFound,
    PromptStoreUnavailable,
    PromptValidationError,
)
from .models import (
    AuditRecord,
    ChangeRequestRecord,
    LabelRecord,
    Message,
    Prompt,
    PromptConfig,
    PromptRecord,
    VersionRecord,
)
from .schema import DEFAULT_PREFIX, Tables, build_tables
from .store import Store, locale_candidates
from .templating import build_renderer

log = logging.getLogger("promptdeck")

V = TypeVar("V", bound=BaseModel)
C = TypeVar("C", bound=BaseModel)
M = TypeVar("M")
R = TypeVar("R")

_UNAVAILABLE = (SQLAlchemyError, OSError, TimeoutError)
Template = "str | list[Message] | list[dict[str, Any]]"


class PromptRegistry:
    """Reads prompts through a small per-process cache; writes go straight to the database.

    Accepts a sync ``Engine`` or an ``AsyncEngine``. Every method has a sync and an ``a``-prefixed
    async form. With an ``AsyncEngine`` the sync forms work from a worker thread (for example a
    sync FastAPI route) once the async side has run, and from plain scripts; they cannot be called
    from inside a running event loop.
    """

    def __init__(
        self,
        engine: Engine | AsyncEngine,
        *,
        environment: str = "production",
        default_locale: str = "en",
        cache_ttl: float = 300.0,
        cache_max_entries: int = 500,
        max_stale: float = 3600.0,
        table_prefix: str = DEFAULT_PREFIX,
        protected_labels: Sequence[str] = ("production",),
        require_distinct_approver: bool = True,
        config_model: type[BaseModel] = PromptConfig,
        metadata_model: type[BaseModel] | None = None,
        default_actor: str = "system",
    ) -> None:
        self.engine = engine
        self.default_actor = default_actor
        self.environment = environment
        self.default_locale = default_locale
        self.cache_ttl = cache_ttl
        self.max_stale = max_stale
        self.protected_labels = frozenset(protected_labels)
        self.config_model = config_model
        self.metadata_model = metadata_model
        self.tables: Tables = build_tables(table_prefix)
        self.store = Store(
            self.tables,
            default_locale=default_locale,
            protected_labels=self.protected_labels,
            require_distinct_approver=require_distinct_approver,
        )
        self.cache: PromptCache[Prompt[Any, Any, Any]] = PromptCache(cache_max_entries)
        self._is_async = isinstance(engine, AsyncEngine)
        self._loop: asyncio.AbstractEventLoop | None = None
        self._otel: Any = None  # None = not probed, False = absent
        self._last_warn = 0.0

    @classmethod
    def in_memory(cls, **settings: Any) -> PromptRegistry:
        """A registry on a private in-memory SQLite database with tables created: for tests and demos."""
        from sqlalchemy import create_engine
        from sqlalchemy.pool import StaticPool

        engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
        reg = cls(engine, **settings)
        reg.create_tables()
        return reg

    # -- engine bridging -------------------------------------------------------------------------

    def _run(self, fn: Callable[..., R], *args: Any, **kwargs: Any) -> R:
        if not self._is_async:
            with cast(Engine, self.engine).begin() as conn:
                return fn(conn, *args, **kwargs)
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            pass
        else:
            raise RuntimeError(
                "promptdeck: this registry wraps an AsyncEngine and a sync method was called from inside a "
                "running event loop. Use the async form (aget, apublish, ...) here; the sync forms work from "
                "threads and plain scripts."
            )
        loop = self._loop
        if loop is not None and loop.is_running():
            return asyncio.run_coroutine_threadsafe(self._arun(fn, *args, **kwargs), loop).result()
        return asyncio.run(self._arun(fn, *args, **kwargs))

    async def _arun(self, fn: Callable[..., R], *args: Any, **kwargs: Any) -> R:
        if not self._is_async:
            return await asyncio.to_thread(self._run, fn, *args, **kwargs)
        self._loop = asyncio.get_running_loop()
        async with cast(AsyncEngine, self.engine).begin() as conn:
            return await conn.run_sync(lambda c: fn(c, *args, **kwargs))

    def create_tables(self) -> None:
        """Create the schema without Alembic (fine for tests and small apps)."""
        self._run(lambda c: self.tables.metadata.create_all(c))

    async def acreate_tables(self) -> None:
        await self._arun(lambda c: self.tables.metadata.create_all(c))

    # -- read path -------------------------------------------------------------------------------

    def get(
        self,
        name: str,
        *,
        label: str | None = None,
        locale: str | None = None,
        default: str | list[Message] | list[dict[str, Any]] | None = None,
        ttl: float | None = None,
    ) -> Prompt[BaseModel, Any, Any]:
        """Resolve a prompt handle. Cache hit: no I/O. Miss: one indexed query."""
        return self._get(name, label, locale, default, ttl, None, None, None, None)

    async def aget(
        self,
        name: str,
        *,
        label: str | None = None,
        locale: str | None = None,
        default: str | list[Message] | list[dict[str, Any]] | None = None,
        ttl: float | None = None,
    ) -> Prompt[BaseModel, Any, Any]:
        return await self._aget(name, label, locale, default, ttl, None, None, None, None)

    def define(
        self,
        name: str,
        *,
        variables: type[V] | None = None,
        config: type[C] | None = None,
        metadata: type[M] | None = None,
    ) -> PromptAccessor[V, C, M]:
        """A typed accessor: ``accessor.get()`` returns ``Prompt[V, C, M]``."""
        return PromptAccessor(self, name, variables, config, metadata)

    def _key(self, name: str, label: str, locale: str, tag: str | None) -> tuple[str, str, str]:
        return (name, label, locale if tag is None else f"{locale}#{tag}")

    def _get(
        self,
        name: str,
        label: str | None,
        locale: str | None,
        default: Any,
        ttl: float | None,
        vars_model: Any,
        cfg_model: Any,
        meta_model: Any,
        tag: str | None,
    ) -> Prompt[Any, Any, Any]:
        label, locale = label or self.environment, locale or self.default_locale
        ttl = self.cache_ttl if ttl is None else ttl
        key = self._key(name, label, locale, tag)
        if ttl > 0 and (h := self.cache.fresh(key)) is not None:
            return self._trace(h)
        build = self._builder(name, label, locale, vars_model, cfg_model, meta_model)
        try:
            if ttl > 0:
                h = self.cache.load(
                    key,
                    lambda: build(
                        self._run(self.store.resolve, name, label, locale_candidates(locale, self.default_locale))
                    ),
                    ttl,
                )
            else:
                h = build(self._run(self.store.resolve, name, label, locale_candidates(locale, self.default_locale)))
        except _UNAVAILABLE as e:
            h = self._on_unavailable(key, name, label, locale, default, ttl, vars_model, cfg_model, meta_model, e)
        except PromptNotFound:
            if default is None:
                raise
            h = self._fallback(name, label, locale, default, vars_model, cfg_model, meta_model)
        return self._trace(h)

    async def _aget(
        self,
        name: str,
        label: str | None,
        locale: str | None,
        default: Any,
        ttl: float | None,
        vars_model: Any,
        cfg_model: Any,
        meta_model: Any,
        tag: str | None,
    ) -> Prompt[Any, Any, Any]:
        label, locale = label or self.environment, locale or self.default_locale
        ttl = self.cache_ttl if ttl is None else ttl
        key = self._key(name, label, locale, tag)
        if ttl > 0 and (h := self.cache.fresh(key)) is not None:
            return self._trace(h)
        build = self._builder(name, label, locale, vars_model, cfg_model, meta_model)
        cands = locale_candidates(locale, self.default_locale)

        async def loader() -> Prompt[Any, Any, Any]:
            return build(await self._arun(self.store.resolve, name, label, cands))

        try:
            h = await (self.cache.aload(key, loader, ttl) if ttl > 0 else loader())
        except _UNAVAILABLE as e:
            h = self._on_unavailable(key, name, label, locale, default, ttl, vars_model, cfg_model, meta_model, e)
        except PromptNotFound:
            if default is None:
                raise
            h = self._fallback(name, label, locale, default, vars_model, cfg_model, meta_model)
        return self._trace(h)

    def _on_unavailable(
        self,
        key: tuple[str, str, str],
        name: str,
        label: str,
        locale: str,
        default: Any,
        ttl: float,
        vars_model: Any,
        cfg_model: Any,
        meta_model: Any,
        err: BaseException,
    ) -> Prompt[Any, Any, Any]:
        now = time.monotonic()
        if now - self._last_warn > 30:
            self._last_warn = now
            log.warning("promptdeck: prompt store unavailable (%s); serving stale/default", err)
        stale = self.cache.stale(key, self.max_stale)
        if stale is not None:
            h = stale if stale.is_fallback else replace(stale, is_fallback=True)
            self.cache.retain(key, h, min(ttl, 5.0) if ttl > 0 else 0)  # back off, keep loaded_at
            return h
        if default is not None:
            return self._fallback(name, label, locale, default, vars_model, cfg_model, meta_model)
        raise PromptStoreUnavailable(f"cannot load prompt {name!r}: {err}") from err

    def _builder(
        self,
        name: str,
        label: str,
        locale: str,
        vars_model: Any,
        cfg_model: Any,
        meta_model: Any,
    ) -> Callable[[dict[str, Any]], Prompt[Any, Any, Any]]:
        cfg_model = cfg_model or self.config_model
        meta_model = meta_model or self.metadata_model

        def build(row: dict[str, Any]) -> Prompt[Any, Any, Any]:
            template = row["template"]
            try:
                config = cfg_model.model_validate(row["config"] or {})
                meta_raw = row["prompt_metadata"] or {}
                metadata = meta_model.model_validate(meta_raw) if meta_model else dict(meta_raw)
            except ValidationError as e:
                raise PromptValidationError(f"prompt {name!r} v{row['version']}: {e}") from e
            return Prompt(
                name=name,
                version=row["version"],
                label=label,
                locale=row["locale"],
                requested_locale=locale,
                type=row["prompt_type"],
                format=row["format"],
                template=template if isinstance(template, str) else [Message(**m) for m in template],
                config=config,
                metadata=metadata,
                variables=tuple(row["variables"] or ()),
                checksum=row["checksum"],
                _renderer=build_renderer(template, row["format"]),
                _variables_model=vars_model,
            )

        return build

    def _fallback(
        self,
        name: str,
        label: str,
        locale: str,
        default: Any,
        vars_model: Any,
        cfg_model: Any,
        meta_model: Any,
    ) -> Prompt[Any, Any, Any]:
        cfg_model = cfg_model or self.config_model
        meta_model = meta_model or self.metadata_model
        raw = (
            default
            if isinstance(default, str)
            else [m.model_dump() if isinstance(m, BaseModel) else dict(m) for m in default]
        )
        return Prompt(
            name=name,
            version=0,
            label=label,
            locale=locale,
            requested_locale=locale,
            type="text" if isinstance(raw, str) else "chat",
            format="python",
            template=raw if isinstance(raw, str) else [Message(**m) for m in raw],
            config=cfg_model.model_construct(),
            metadata=meta_model.model_construct() if meta_model else {},
            variables=(),
            is_fallback=True,
            _renderer=build_renderer(raw, "python"),
            _variables_model=vars_model,
        )

    def _trace(self, h: Prompt[Any, Any, Any]) -> Prompt[Any, Any, Any]:
        if self._otel is None:
            try:
                from opentelemetry import trace as _t

                self._otel = _t
            except ImportError:
                self._otel = False
        if self._otel:
            span = self._otel.get_current_span()
            if span.is_recording():
                span.set_attributes(h.trace_attributes())
        return h

    # -- health ----------------------------------------------------------------------------------

    def health(self) -> dict[str, Any]:
        return self._health(self._safe(lambda: self._run(self.store.health)))

    async def ahealth(self) -> dict[str, Any]:
        try:
            ok = await self._arun(self.store.health)
        except _UNAVAILABLE as e:
            ok = False
            log.warning("promptdeck health: %s", e)
        return self._health(ok)

    def _safe(self, fn: Callable[[], bool]) -> bool:
        try:
            return fn()
        except _UNAVAILABLE as e:
            log.warning("promptdeck health: %s", e)
            return False

    def _health(self, ok: bool) -> dict[str, Any]:
        return {"database": "ok" if ok else "unavailable", "cache": self.cache.stats()}

    # -- management API (sync + async) -----------------------------------------------------------
    # Writes that change what a label resolves to clear this worker's cache for the prompt.

    def create_prompt(
        self,
        name: str,
        type: str = "text",
        *,
        actor: str | None = None,
        description: str | None = None,
        tags: Sequence[str] = (),
        metadata: dict[str, Any] | None = None,
    ) -> PromptRecord:
        self._check_metadata(metadata)
        return self._run(self.store.create_prompt, name, type, self._actor(actor), description, tags, metadata)

    async def acreate_prompt(
        self,
        name: str,
        type: str = "text",
        *,
        actor: str | None = None,
        description: str | None = None,
        tags: Sequence[str] = (),
        metadata: dict[str, Any] | None = None,
    ) -> PromptRecord:
        self._check_metadata(metadata)
        return await self._arun(self.store.create_prompt, name, type, self._actor(actor), description, tags, metadata)

    def get_prompt(self, name: str) -> PromptRecord:
        return self._run(self.store.get_prompt, name)

    async def aget_prompt(self, name: str) -> PromptRecord:
        return await self._arun(self.store.get_prompt, name)

    def list_prompts(
        self,
        *,
        q: str | None = None,
        tag: str | None = None,
        metadata: dict[str, Any] | None = None,
        include_archived: bool = False,
    ) -> list[PromptRecord]:
        return self._run(self.store.list_prompts, q=q, tag=tag, metadata=metadata, include_archived=include_archived)

    async def alist_prompts(
        self,
        *,
        q: str | None = None,
        tag: str | None = None,
        metadata: dict[str, Any] | None = None,
        include_archived: bool = False,
    ) -> list[PromptRecord]:
        return await self._arun(
            self.store.list_prompts, q=q, tag=tag, metadata=metadata, include_archived=include_archived
        )

    def update_metadata(self, name: str, metadata: dict[str, Any], *, actor: str | None = None) -> PromptRecord:
        self._check_metadata(metadata)
        r = self._run(self.store.update_metadata, name, metadata, self._actor(actor))
        self.cache.invalidate(name)
        return r

    async def aupdate_metadata(self, name: str, metadata: dict[str, Any], *, actor: str | None = None) -> PromptRecord:
        self._check_metadata(metadata)
        r = await self._arun(self.store.update_metadata, name, metadata, self._actor(actor))
        self.cache.invalidate(name)
        return r

    def update_prompt(
        self, name: str, *, actor: str | None = None, description: str | None = None, tags: Sequence[str] | None = None
    ) -> PromptRecord:
        return self._run(self.store.update_prompt, name, self._actor(actor), description=description, tags=tags)

    async def aupdate_prompt(
        self, name: str, *, actor: str | None = None, description: str | None = None, tags: Sequence[str] | None = None
    ) -> PromptRecord:
        return await self._arun(self.store.update_prompt, name, self._actor(actor), description=description, tags=tags)

    def archive(self, name: str, *, actor: str | None = None, archived: bool = True) -> PromptRecord:
        r = self._run(self.store.archive, name, self._actor(actor), archived)
        self.cache.invalidate(name)
        return r

    async def aarchive(self, name: str, *, actor: str | None = None, archived: bool = True) -> PromptRecord:
        r = await self._arun(self.store.archive, name, self._actor(actor), archived)
        self.cache.invalidate(name)
        return r

    def create_version(
        self,
        name: str,
        template: str | list[dict[str, Any]],
        *,
        format: str = "python",
        message: str,
        actor: str | None = None,
        locale: str | None = None,
        config: dict[str, Any] | None = None,
    ) -> VersionRecord:
        self._check_config(config)
        r = self._run(
            self.store.create_version,
            name,
            template,
            format=format,
            message=message,
            actor=self._actor(actor),
            locale=locale,
            config=config,
        )
        self.cache.invalidate(name)
        return r

    async def acreate_version(
        self,
        name: str,
        template: str | list[dict[str, Any]],
        *,
        format: str = "python",
        message: str,
        actor: str | None = None,
        locale: str | None = None,
        config: dict[str, Any] | None = None,
    ) -> VersionRecord:
        self._check_config(config)
        r = await self._arun(
            self.store.create_version,
            name,
            template,
            format=format,
            message=message,
            actor=self._actor(actor),
            locale=locale,
            config=config,
        )
        self.cache.invalidate(name)
        return r

    def history(self, name: str, locale: str | None = None) -> list[VersionRecord]:
        return self._run(self.store.history, name, locale)

    async def ahistory(self, name: str, locale: str | None = None) -> list[VersionRecord]:
        return await self._arun(self.store.history, name, locale)

    def diff(self, name: str, a: int, b: int, locale: str | None = None) -> str:
        return self._run(self.store.diff, name, a, b, locale)

    async def adiff(self, name: str, a: int, b: int, locale: str | None = None) -> str:
        return await self._arun(self.store.diff, name, a, b, locale)

    def labels(self, name: str, locale: str | None = None) -> list[LabelRecord]:
        return self._run(self.store.labels, name, locale)

    async def alabels(self, name: str, locale: str | None = None) -> list[LabelRecord]:
        return await self._arun(self.store.labels, name, locale)

    def label_history(self, name: str, label: str, locale: str | None = None) -> list[dict[str, Any]]:
        return self._run(self.store.label_history, name, label, locale)

    async def alabel_history(self, name: str, label: str, locale: str | None = None) -> list[dict[str, Any]]:
        return await self._arun(self.store.label_history, name, label, locale)

    def publish(
        self,
        name: str,
        version: int,
        label: str,
        *,
        actor: str | None = None,
        locale: str | None = None,
        expected_current: int | None = None,
        reason: str | None = None,
        force: bool = False,
    ) -> LabelRecord:
        r = self._run(
            self.store.publish,
            name,
            version,
            label,
            actor=self._actor(actor),
            locale=locale,
            expected_current=expected_current,
            reason=reason,
            force=force,
        )
        self.cache.invalidate(name)
        return r

    async def apublish(
        self,
        name: str,
        version: int,
        label: str,
        *,
        actor: str | None = None,
        locale: str | None = None,
        expected_current: int | None = None,
        reason: str | None = None,
        force: bool = False,
    ) -> LabelRecord:
        r = await self._arun(
            self.store.publish,
            name,
            version,
            label,
            actor=self._actor(actor),
            locale=locale,
            expected_current=expected_current,
            reason=reason,
            force=force,
        )
        self.cache.invalidate(name)
        return r

    def rollback(
        self, name: str, label: str, *, actor: str | None = None, locale: str | None = None, reason: str | None = None
    ) -> LabelRecord:
        r = self._run(self.store.rollback, name, label, actor=self._actor(actor), locale=locale, reason=reason)
        self.cache.invalidate(name)
        return r

    async def arollback(
        self, name: str, label: str, *, actor: str | None = None, locale: str | None = None, reason: str | None = None
    ) -> LabelRecord:
        r = await self._arun(self.store.rollback, name, label, actor=self._actor(actor), locale=locale, reason=reason)
        self.cache.invalidate(name)
        return r

    def request_change(
        self,
        name: str,
        version: int,
        label: str,
        *,
        actor: str | None = None,
        locale: str | None = None,
        comment: str | None = None,
    ) -> ChangeRequestRecord:
        return self._run(
            self.store.request_change, name, version, label, actor=self._actor(actor), locale=locale, comment=comment
        )

    async def arequest_change(
        self,
        name: str,
        version: int,
        label: str,
        *,
        actor: str | None = None,
        locale: str | None = None,
        comment: str | None = None,
    ) -> ChangeRequestRecord:
        return await self._arun(
            self.store.request_change, name, version, label, actor=self._actor(actor), locale=locale, comment=comment
        )

    def approve(self, cr_id: int, *, actor: str | None = None, comment: str | None = None) -> ChangeRequestRecord:
        return self._run(self.store.approve, cr_id, self._actor(actor), comment)

    async def aapprove(
        self, cr_id: int, *, actor: str | None = None, comment: str | None = None
    ) -> ChangeRequestRecord:
        return await self._arun(self.store.approve, cr_id, self._actor(actor), comment)

    def reject(self, cr_id: int, *, actor: str | None = None, comment: str | None = None) -> ChangeRequestRecord:
        return self._run(self.store.reject, cr_id, self._actor(actor), comment)

    async def areject(self, cr_id: int, *, actor: str | None = None, comment: str | None = None) -> ChangeRequestRecord:
        return await self._arun(self.store.reject, cr_id, self._actor(actor), comment)

    def list_change_requests(self, name: str | None = None, status: str | None = None) -> list[ChangeRequestRecord]:
        return self._run(self.store.list_change_requests, name, status)

    async def alist_change_requests(
        self, name: str | None = None, status: str | None = None
    ) -> list[ChangeRequestRecord]:
        return await self._arun(self.store.list_change_requests, name, status)

    def audit(
        self,
        *,
        target_type: str | None = None,
        target_id: str | None = None,
        actor: str | None = None,
        limit: int = 200,
    ) -> list[AuditRecord]:
        return self._run(
            self.store.audit, target_type=target_type, target_id=target_id, actor=actor, limit=limit
        )

    async def aaudit(
        self,
        *,
        target_type: str | None = None,
        target_id: str | None = None,
        actor: str | None = None,
        limit: int = 200,
    ) -> list[AuditRecord]:
        return await self._arun(
            self.store.audit, target_type=target_type, target_id=target_id, actor=actor, limit=limit
        )

    def export(self, names: Sequence[str] | None = None) -> dict[str, Any]:
        return self._run(self.store.export_all, names)

    async def aexport(self, names: Sequence[str] | None = None) -> dict[str, Any]:
        return await self._arun(self.store.export_all, names)

    def import_prompts(
        self, data: dict[str, Any], *, actor: str | None = None, set_labels: bool = True
    ) -> dict[str, int]:
        r = self._run(self.store.import_all, data, self._actor(actor), set_labels=set_labels)
        self.cache.invalidate()
        return r

    async def aimport_prompts(
        self, data: dict[str, Any], *, actor: str | None = None, set_labels: bool = True
    ) -> dict[str, int]:
        r = await self._arun(self.store.import_all, data, self._actor(actor), set_labels=set_labels)
        self.cache.invalidate()
        return r

    import_ = import_prompts  # old name, kept for compatibility
    aimport = aimport_prompts

    def _actor(self, actor: str | None) -> str:
        return actor or self.default_actor

    # -- validation helpers ----------------------------------------------------------------------

    def _check_config(self, config: dict[str, Any] | None) -> None:
        if config:
            try:
                self.config_model.model_validate(config)
            except ValidationError as e:
                raise PromptValidationError(f"config: {e}") from e

    def _check_metadata(self, metadata: dict[str, Any] | None) -> None:
        if metadata and self.metadata_model is not None:
            try:
                self.metadata_model.model_validate(metadata)
            except ValidationError as e:
                raise PromptValidationError(f"metadata: {e}") from e

    def validate_version(
        self,
        template: str | list[dict[str, Any]],
        format: str,
        config: dict[str, Any] | None,
        metadata: dict[str, Any] | None,
    ) -> None:
        """Raise ``PromptValidationError``/``PromptRenderError`` for bad input (used by the UI)."""
        self._check_config(config)
        self._check_metadata(metadata)
        build_renderer(template, format)


class PromptAccessor(Generic[V, C, M]):
    """Typed accessor returned by :meth:`PromptRegistry.define`."""

    __slots__ = ("registry", "name", "variables", "config", "metadata", "_tag")

    def __init__(
        self,
        registry: PromptRegistry,
        name: str,
        variables: type[V] | None,
        config: type[C] | None,
        metadata: type[M] | None,
    ) -> None:
        self.registry, self.name = registry, name
        self.variables, self.config, self.metadata = variables, config, metadata
        self._tag = "/".join(getattr(m, "__qualname__", "-") for m in (variables, config, metadata))

    def get(
        self,
        *,
        label: str | None = None,
        locale: str | None = None,
        default: str | list[Message] | list[dict[str, Any]] | None = None,
        ttl: float | None = None,
    ) -> Prompt[V, C, M]:
        return self.registry._get(
            self.name, label, locale, default, ttl, self.variables, self.config, self.metadata, self._tag
        )

    async def aget(
        self,
        *,
        label: str | None = None,
        locale: str | None = None,
        default: str | list[Message] | list[dict[str, Any]] | None = None,
        ttl: float | None = None,
    ) -> Prompt[V, C, M]:
        return await self.registry._aget(
            self.name, label, locale, default, ttl, self.variables, self.config, self.metadata, self._tag
        )


__all__ = ["PromptRegistry", "PromptAccessor", "Connection", "Awaitable", "PromptDeckError"]
