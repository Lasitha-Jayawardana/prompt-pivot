# prompt-pivot

Store, version, edit and publish LLM prompts at runtime from inside your FastAPI app, using the
PostgreSQL or MySQL database you already have. No extra server, no vendor cloud, no background
workers.

- **One call in agent code**: `prompts.get("support/agent", locale="fr")` returns an immutable,
  typed handle with the template, model config, metadata and version.
- **Edit without a deploy**: a built-in admin UI (server-rendered, no build step, no CDN) to edit,
  preview, diff, publish, approve and roll back. Every change is versioned, attributed and audited.
- **Fast and resilient**: lazy per-process LRU cache (a hit is under 1 µs, no I/O), one indexed query
  on a miss, single-flight loading, and stale-while-error serving if the database blips.
- **Small**: four runtime dependencies you already have in a FastAPI app (SQLAlchemy, Pydantic,
  Jinja2, FastAPI). About 3,000 lines including the UI. `py.typed`, mypy strict clean.

Full feature, use-case and UI walkthrough: [docs/guide.md](docs/guide.md).

## Install

```bash
pip install prompt-pivot
# optional extras
pip install "prompt-pivot[postgres]"   # asyncpg + psycopg
pip install "prompt-pivot[mysql]"      # aiomysql + pymysql
pip install "prompt-pivot[alembic]"    # versioned schema migrations (recommended in production)
pip install "prompt-pivot[yaml]"       # YAML export/import in the CLI
pip install "prompt-pivot[otel]"       # OpenTelemetry span attributes
```

Python 3.10+, SQLAlchemy 2, Pydantic 2, FastAPI 0.110+. PostgreSQL 13+ and MySQL 8+ (SQLite works
for local development and tests).

## Quickstart (10 minutes)

**1. Create the schema** (once per database, alongside your own migrations):

```bash
promptpivot --url postgresql+psycopg://user:pass@host/db migrate
```

or from code: `from promptpivot.migrations import upgrade; upgrade(engine)`.

**2. Create the registry and mount the admin UI:**

```python
from fastapi import Depends, FastAPI
from sqlalchemy.ext.asyncio import create_async_engine
from promptpivot import PromptRegistry, Principal
from promptpivot.fastapi import admin_router

engine = create_async_engine("postgresql+asyncpg://user:pass@host/db")   # async or sync engine
prompts = PromptRegistry(engine, environment="production")

async def principal(user=Depends(get_current_user)) -> Principal:        # your existing auth
    return Principal(id=user.id, name=user.email, permissions=map_roles(user.roles))

app = FastAPI()
app.include_router(admin_router(prompts, principal=principal), prefix="/admin/prompts")
```

Nothing is exposed unless you mount the router, and the router always runs your `principal`
dependency first. For a first local run, `from promptpivot.fastapi import dev_principal` grants
every permission; it only works when `PROMPTPIVOT_DEV_UI=1` is set, so it cannot ship by accident.

**3. Read prompts in agent code:**

```python
p = await prompts.aget("support/agent", locale="fr-CA")      # fr-CA -> fr -> en
messages = p.compile_messages(customer_name="Alice", plan="Pro")   # list[Message]; compile_text() for text prompts
response = await llm.chat(model=p.config.model, temperature=p.config.temperature, messages=messages)
span.set_attributes(p.trace_attributes())                    # prompt.name / version / label / locale / is_fallback

# sync code works too, with an optional in-code default used only when nothing else can be served
p = prompts.get("greeting", default="Hello {customer_name}!")
```

**4. Typed prompts (recommended):**

```python
from pydantic import BaseModel

class SupportVars(BaseModel):
    customer_name: str
    plan: str

class SupportMeta(BaseModel):
    owner: str
    team: str | None = None

support_agent = prompts.define("support/agent", variables=SupportVars, metadata=SupportMeta)

p = await support_agent.aget(locale=user.locale)              # Prompt[SupportVars, PromptConfig, SupportMeta]
messages = p.compile(SupportVars(customer_name="Alice", plan="Pro"))
owner: str = p.metadata.owner
```

`compile(**kwargs)` validates the keyword arguments against the variables model and raises
`PromptValidationError` on a mismatch. A custom `config=` model types `p.config` the same way.

**5. Open `/admin/prompts`** to edit, preview, publish and roll back. See [examples/app.py](examples/app.py)
for a runnable demo (`uvicorn examples.app:app --reload`).

## Concepts

| Concept | Meaning |
| --- | --- |
| **Prompt** | A named, hierarchical unit (`support/triage/classify`) of type `text` or `chat`, with tags and free-form JSON metadata. |
| **Version** | Immutable snapshot of template, format (`python` or `jinja`), config, variables, commit message and author. Each save creates the next number. |
| **Locale** | BCP 47 variant (`en`, `fr`, `pt-BR`) of a prompt, with its own versions and labels. Resolution: exact tag, base language, then the default locale. |
| **Label** | A named pointer to one version of one locale: `production`, `staging`, `latest` (moves on save) or any custom name. Code reads labels, never raw version numbers. |
| **Change request** | Required to move a protected label (default: `production`). One approver, who must differ from the author. |

### Template formats

| Format | Example | Rules |
| --- | --- | --- |
| `python` | `Help {customer_name} on the {plan} plan.` | Named fields only. No attribute access, indexing or conversions. `{{` and `}}` for literal braces. Plain format specs such as `{n:03d}` are allowed. |
| `jinja` | `Help {{ customer_name }}{% if plan == "Pro" %} with priority{% endif %}.` | Sandboxed environment, strict undefined, compiled once per version. |

Missing variables raise `PromptRenderError` in both formats.

### The handle

`get()` / `aget()` return a frozen `Prompt` with: `name`, `version`, `label`, `locale`,
`requested_locale`, `type`, `format`, `template`, `config`, `metadata`, `variables`, `is_fallback`,
`checksum`, plus `compile(...)`, `compile_text(...)`, `compile_messages(...)` and
`trace_attributes()`. `compile()` returns `str | list[Message]`; the two typed variants check the
prompt type and return `str` or `list[Message]`. A handle never changes after it is returned, so a
publish mid-request cannot change what that request renders.

## Caching and resilience

- Lazy: a prompt is loaded on first use; startup runs zero queries and starts no threads.
- Per-process LRU keyed by `(name, label, locale)`, bounded by `cache_max_entries` (500).
- `cache_ttl` (default 300 s) bounds propagation: after a publish, every worker serves the new
  version within the TTL. The worker that published serves it immediately. Pass `ttl=` per call;
  `ttl=0` bypasses the cache.
- Concurrent misses for one key share a single query (sync threads and asyncio tasks).
- If the database errors, an expired entry is served for up to `max_stale` (1 hour) with
  `is_fallback=True`, retried at most every 5 s, and a rate-limited warning is logged. With nothing
  cached, `default=` is used; otherwise `PromptStoreUnavailable` is raised.

Steady-state load is at most one indexed query per hot key per TTL per worker.

### Sync and async engines

Every method has a sync form and an `a`-prefixed async form (`get`/`aget`, `publish`/`apublish`).
With a sync `Engine` the async forms run the query in a thread. With an `AsyncEngine` the sync forms
work from worker threads once the event loop has run (for example in sync FastAPI routes or
background threads) and from plain scripts; calling them from inside a running coroutine raises
`RuntimeError` so the loop is never blocked.

## Settings

| Setting | Default | Description |
| --- | --- | --- |
| `engine` | required | SQLAlchemy `Engine` or `AsyncEngine` |
| `environment` | `production` | Default label for `get()` |
| `default_locale` | `en` | Final locale fallback |
| `cache_ttl` | `300` | Seconds a cache entry is fresh; `0` disables caching |
| `cache_max_entries` | `500` | LRU bound per process |
| `max_stale` | `3600` | How long an expired entry may be served while the database is down |
| `table_prefix` | `promptpivot_` | Prefix for all tables and the Alembic version table |
| `protected_labels` | `("production",)` | Labels that require an approved change request |
| `require_distinct_approver` | `True` | Approver must differ from the author |
| `config_model` | `PromptConfig` | Pydantic model for `handle.config` (extra keys allowed) |
| `metadata_model` | `None` | Pydantic model for `handle.metadata` (a `dict` when unset) |
| `default_actor` | `system` | Actor recorded when a write does not pass `actor=` |

## Management API

Most teams change prompts in the UI and never call these; they back the UI, the CLI and scripts.
Available on the registry in sync and async forms; writes take `actor=` (default: the registry's
`default_actor`, `"system"`):

`create_prompt`, `get_prompt`, `list_prompts`, `update_prompt`, `update_metadata`, `archive`,
`create_version`, `history`, `diff`, `labels`, `label_history`, `publish`, `rollback`,
`request_change`, `approve`, `reject`, `list_change_requests`, `audit`, `export`, `import_prompts`,
`health`. `PromptRegistry.in_memory()` gives a throwaway SQLite registry for tests.

`create_version(name, template, *, format="python", message, locale=None, config=None)` keeps the
previous version's config when `config` is omitted (pass `{}` to clear it) and accepts `Message`
objects or dicts for chat templates. The returned record carries `warning` when a locale variant's
variables differ from the default locale's production version.

`publish(name, version, label, *, actor, locale=None, expected_current=None, reason=None, force=False)`
moves a label with an optimistic lock (`PromptConflict` if someone else moved it first). For a
protected label it requires an approved change request unless `force=True` (break-glass, recorded
in the audit log with the reason). `rollback` moves a label to the version it pointed to before its
last move; it is an undo, so a second rollback re-applies the move. The UI shows the destination
(`Rollback production: v3 → v2`) before you click.

## Admin UI and REST API

Mount `admin_router(registry, principal=..., ui=True, include_in_schema=True)`.

- UI: list and search, editor with format selector and live variable detection, JSON config and
  metadata editors validated against your models, preview with sample variables, version history
  and diffs, publish, request review, approve, reject, one-click rollback, audit log, and an
  Import page (paste an export) plus an Export download for moving prompts between environments.
- REST API under `<prefix>/api/...` (listed in the host's OpenAPI unless `include_in_schema=False`):
  `GET api/health`, `GET|POST api/prompts`, `GET api/prompts/{name}`,
  `POST api/prompts/{name}/versions|publish|rollback|change-requests|preview|archive`,
  `PUT api/prompts/{name}/metadata`, `GET api/prompts/{name}/diff`, `GET api/change-requests`,
  `POST api/change-requests/{id}/approve|reject`, `GET api/audit`, `GET api/export`,
  `POST api/import`.

### Permissions

Your `principal` dependency returns a `Principal(id, name, permissions)`. Map your roles to:

| Permission | Allows |
| --- | --- |
| `prompts:read` | View prompts, versions, diffs, previews, health |
| `prompts:edit` | Create prompts, save versions, edit metadata, open change requests |
| `prompts:publish:<label>` | Move that label (publish, rollback) |
| `prompts:approve` | Approve or reject change requests |
| `prompts:admin` | Everything, plus archive, audit log and break-glass publish |

### Security defaults

Not mounted by default; no built-in users or credentials; CSRF double-submit cookie on every
mutating form; JSON-only API mutations; sandboxed rendering for both formats; prompt content is
never sent to end users by the package.

### Migrating existing prompts

Most teams start with prompts hardcoded in Python. Paste each one into *New prompt* → *New
version* in the UI, or write them once as an export file and use *Import* (UI), `promptpivot import`
(CLI) or `POST api/import`. Then replace the constant in code with `prompts.get("name")` and keep
the old string as `default=` until you trust the database path.

## CLI

```bash
export PROMPTPIVOT_DATABASE_URL=postgresql+psycopg://user:pass@host/db
promptpivot migrate                                   # create or upgrade the schema
promptpivot list                                      # prompts and their labels
promptpivot export -o prompts.yaml                    # backup / copy between environments (.json or .yaml)
promptpivot import prompts.yaml [--no-labels]         # versions matched by checksum, nothing duplicated
promptpivot publish support/agent 7 staging --locale fr
promptpivot publish support/agent 7 production --force --reason "incident 123"
promptpivot rollback support/agent production
```

Async URLs (`+asyncpg`, `+aiomysql`) work too. `--prefix` or `PROMPTPIVOT_TABLE_PREFIX` selects the
table prefix; `--actor` sets the audit actor (defaults to `$USER`).

## Migrations

Tables: `prompts`, `versions`, `labels`, `label_history`, `change_requests`, `audit_log`, all with
the configurable prefix and portable types (JSON, Text, BigInteger). Migrations ship as Alembic
scripts with their own version table (`<prefix>alembic_version`) so they coexist with your app's.
`promptpivot migrate` or `promptpivot.migrations.upgrade(engine)` runs them; without the `[alembic]`
extra they fall back to `create_all`, which is fine for development.

## Production checklist

1. Install `promptpivot[alembic]` and run `promptpivot migrate` in your deploy pipeline.
2. Mount the router behind your real auth; give `prompts:publish:production` only to approvers or
   on-call, and `prompts:admin` to very few people.
3. Serve the admin UI over HTTPS (the CSRF cookie is marked `secure` on HTTPS requests).
4. Pick `cache_ttl` to match how fast you need publishes to propagate; 30 to 300 s is typical.
5. Give business-critical prompts a `default=` in code so brand-new workers can start during a
   database outage.
6. Forward `prompt.*` span attributes (automatic when `opentelemetry-api` is installed) so every LLM
   span records which version produced it.
7. Watch `GET <prefix>/api/health` (database reachability, cache size and hit ratio).

## Rollback runbook

1. Open `/admin/prompts/p/<name>?locale=<locale>` (or run `promptpivot rollback <name> production`).
2. Click **Rollback production**. The label moves back to its previous version in one transaction;
   the audit log records who did it and when.
3. The worker that handled the request serves the old version at once; all other workers within
   `cache_ttl`. Verify with `GET api/prompts/<name>` (labels) and your LLM spans' `prompt.version`.
4. Rolling back does not need a change request: it only re-targets a version that was already
   approved for that label.

## Using a local checkout in other projects

While iterating on promptpivot itself, install it editable so every other project on the machine
picks up your edits without reinstalling:

```bash
# in the other project (pip or uv)
pip install -e /path/to/prompt-pivot
uv add --editable /path/to/prompt-pivot        # uv-managed project
```

Straight from GitHub without a checkout: `pip install "prompt-pivot @ git+https://github.com/Lasitha-Jayawardana/prompt-pivot.git"`.

## Development

```bash
uv venv && uv pip install -e . --group dev
pytest                      # SQLite, sync and async
mypy && ruff check .
PROMPTPIVOT_TEST_POSTGRES_URL=postgresql+psycopg://... PROMPTPIVOT_TEST_MYSQL_URL=mysql+pymysql://... pytest
```

License: Apache-2.0.
