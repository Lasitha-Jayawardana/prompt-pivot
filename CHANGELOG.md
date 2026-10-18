# Changelog

## 0.1.1 (2026-10-19)

Fix: a plain `pip install prompt-pivot` failed to import because SQLAlchemy's asyncio support needs
`greenlet`; the dependency is now `sqlalchemy[asyncio]`.

## 0.1.0 (2026-10-19)

Distribution and CLI name `prompt-pivot`, import name `promptpivot` (earlier working names were
too similar to existing PyPI projects).

First release. Prompts, immutable versions, locales with fallback, labels with optimistic locking,
change requests with a single approver, append-only audit, per-process TTL+LRU cache with
single-flight and stale-while-error, typed handles via `define()`, python and jinja formats,
FastAPI admin UI and REST API with CSRF, CLI (`migrate`, `export`, `import`, `publish`,
`rollback`, `list`), Alembic migration `0001`.

Developer-experience pass before release: `create_version` keeps the previous config when none is
given and returns a record with `warning`; chat templates accept `Message` objects;
`compile_text()` / `compile_messages()`; `default_actor`; `PromptRegistry.in_memory()`;
`import_prompts` (old `import_` kept); UI Import page and Export download (`api/export`,
`api/import`); rollback buttons show the destination; inline reason and locale fields instead of
browser dialogs; `dev_principal` guarded by `PROMPTPIVOT_DEV_UI=1`.
