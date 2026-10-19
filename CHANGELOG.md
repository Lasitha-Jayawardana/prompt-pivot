# Changelog

## Unreleased

- Per-version `notes` (JSON) in the API, UI, CLI export/import and `create_version(notes=...)`.
- Prompt names are case-sensitive on MySQL too (binary collation on the name column).
- List page and `GET api/prompts` filter on top-level metadata (`metadata=owner=cx,team=tier1`).
- Locale tabs flag variants not updated since the default locale's last production change;
  `GET api/prompts/{name}` returns `stale_locales`; `registry.stale_locales(name)`.
- Migration `0002`; `migrate` now stamps fresh databases at head and upgrades existing ones.

## 0.1.3 (2026-10-19)

- `python` format: only `{name}` / `{name:spec}` with a plain identifier is a variable; every other
  brace (JSON examples, `{a.b}`, stray braces) is kept as text. `{{name}}` prints a literal `{name}`
  (the old `{{`/`}}` escapes broke nested JSON).
- `default=` templates written in Jinja no longer crash: the format is guessed from Jinja tags, and
  `get`/`aget`/`define().get` accept `default_format="python" | "jinja"`. Fallback handles now
  report their `format` and `variables`.

## 0.1.2 (2026-10-19)

Fix: the `[mysql]` extra now includes `pymysql[rsa]` (the `cryptography` package), which MySQL 8's
default `caching_sha2_password` authentication requires for the async driver.

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
