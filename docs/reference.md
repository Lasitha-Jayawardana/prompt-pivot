# prompt-pivot API reference

Generated from `promptpivot` 0.1.3 by `docs/gen_reference.py`. Do not edit by hand.

Import everything below from `promptpivot` unless a module path is shown.

## Registry

### `PromptRegistry`

Reads prompts through a small per-process cache; writes go straight to the database.

Accepts a sync ``Engine`` or an ``AsyncEngine``. Every method has a sync and an ``a``-prefixed
async form. With an ``AsyncEngine`` the sync forms work from a worker thread (for example a
sync FastAPI route) once the async side has run, and from plain scripts; they cannot be called
from inside a running event loop.

#### `async PromptRegistry.aapprove(self, cr_id: 'int', *, actor: 'str | None' = None, comment: 'str | None' = None) -> 'ChangeRequestRecord'`

Async form of :meth:`approve`.

#### `async PromptRegistry.aarchive(self, name: 'str', *, actor: 'str | None' = None, archived: 'bool' = True) -> 'PromptRecord'`

Async form of :meth:`archive`.

#### `async PromptRegistry.aaudit(self, *, target_type: 'str | None' = None, target_id: 'str | None' = None, actor: 'str | None' = None, limit: 'int' = 200) -> 'list[AuditRecord]'`

Async form of :meth:`audit`.

#### `async PromptRegistry.acreate_prompt(self, name: 'str', type: 'str' = 'text', *, actor: 'str | None' = None, description: 'str | None' = None, tags: 'Sequence[str]' = (), metadata: 'dict[str, Any] | None' = None) -> 'PromptRecord'`

Async form of :meth:`create_prompt`.

#### `async PromptRegistry.acreate_tables(self) -> 'None'`

Async form of :meth:`create_tables`.

#### `async PromptRegistry.acreate_version(self, name: 'str', template: 'str | list[dict[str, Any]]', *, format: 'str' = 'python', message: 'str', actor: 'str | None' = None, locale: 'str | None' = None, config: 'dict[str, Any] | None' = None, notes: 'dict[str, Any] | None' = None) -> 'VersionRecord'`

Async form of :meth:`create_version`.

#### `async PromptRegistry.adiff(self, name: 'str', a: 'int', b: 'int', locale: 'str | None' = None) -> 'str'`

Async form of :meth:`diff`.

#### `async PromptRegistry.aexport(self, names: 'Sequence[str] | None' = None) -> 'dict[str, Any]'`

Async form of :meth:`export`.

#### `async PromptRegistry.aget(self, name: 'str', *, label: 'str | None' = None, locale: 'str | None' = None, default: 'str | list[Message] | list[dict[str, Any]] | None' = None, ttl: 'float | None' = None, default_format: 'str | None' = None) -> 'Prompt[BaseModel, Any, Any]'`

Async form of :meth:`get`.

#### `async PromptRegistry.aget_prompt(self, name: 'str') -> 'PromptRecord'`

Async form of :meth:`get_prompt`.

#### `async PromptRegistry.ahealth(self) -> 'dict[str, Any]'`

Async form of :meth:`health`.

#### `async PromptRegistry.ahistory(self, name: 'str', locale: 'str | None' = None) -> 'list[VersionRecord]'`

Async form of :meth:`history`.

#### `async PromptRegistry.aimport(self, data: 'dict[str, Any]', *, actor: 'str | None' = None, set_labels: 'bool' = True) -> 'dict[str, int]'`

Async form of :meth:`import_prompts`.

#### `async PromptRegistry.aimport_prompts(self, data: 'dict[str, Any]', *, actor: 'str | None' = None, set_labels: 'bool' = True) -> 'dict[str, int]'`

Async form of :meth:`import_prompts`.

#### `async PromptRegistry.alabel_history(self, name: 'str', label: 'str', locale: 'str | None' = None) -> 'list[dict[str, Any]]'`

Async form of :meth:`label_history`.

#### `async PromptRegistry.alabels(self, name: 'str', locale: 'str | None' = None) -> 'list[LabelRecord]'`

Async form of :meth:`labels`.

#### `async PromptRegistry.alist_change_requests(self, name: 'str | None' = None, status: 'str | None' = None) -> 'list[ChangeRequestRecord]'`

Async form of :meth:`list_change_requests`.

#### `async PromptRegistry.alist_prompts(self, *, q: 'str | None' = None, tag: 'str | None' = None, metadata: 'dict[str, Any] | None' = None, include_archived: 'bool' = False) -> 'list[PromptRecord]'`

Async form of :meth:`list_prompts`.

#### `PromptRegistry.approve(self, cr_id: 'int', *, actor: 'str | None' = None, comment: 'str | None' = None) -> 'ChangeRequestRecord'`

Approve an open change request. The approver must differ from the author when ``require_distinct_approver``
is on.

#### `async PromptRegistry.apublish(self, name: 'str', version: 'int', label: 'str', *, actor: 'str | None' = None, locale: 'str | None' = None, expected_current: 'int | None' = None, reason: 'str | None' = None, force: 'bool' = False) -> 'LabelRecord'`

Async form of :meth:`publish`.

#### `PromptRegistry.archive(self, name: 'str', *, actor: 'str | None' = None, archived: 'bool' = True) -> 'PromptRecord'`

Hide a prompt from lists and from ``get()`` (``archived=False`` restores). History is kept.

#### `async PromptRegistry.areject(self, cr_id: 'int', *, actor: 'str | None' = None, comment: 'str | None' = None) -> 'ChangeRequestRecord'`

Async form of :meth:`reject`.

#### `async PromptRegistry.arequest_change(self, name: 'str', version: 'int', label: 'str', *, actor: 'str | None' = None, locale: 'str | None' = None, comment: 'str | None' = None) -> 'ChangeRequestRecord'`

Async form of :meth:`request_change`.

#### `async PromptRegistry.arollback(self, name: 'str', label: 'str', *, actor: 'str | None' = None, locale: 'str | None' = None, reason: 'str | None' = None) -> 'LabelRecord'`

Async form of :meth:`rollback`.

#### `async PromptRegistry.astale_locales(self, name: 'str') -> 'list[str]'`

Async form of :meth:`stale_locales`.

#### `PromptRegistry.audit(self, *, target_type: 'str | None' = None, target_id: 'str | None' = None, actor: 'str | None' = None, limit: 'int' = 200) -> 'list[AuditRecord]'`

Audit records, newest first, filtered by target type, target id prefix and/or actor.

#### `async PromptRegistry.aupdate_metadata(self, name: 'str', metadata: 'dict[str, Any]', *, actor: 'str | None' = None) -> 'PromptRecord'`

Async form of :meth:`update_metadata`.

#### `async PromptRegistry.aupdate_prompt(self, name: 'str', *, actor: 'str | None' = None, description: 'str | None' = None, tags: 'Sequence[str] | None' = None) -> 'PromptRecord'`

Async form of :meth:`update_prompt`.

#### `PromptRegistry.create_prompt(self, name: 'str', type: 'str' = 'text', *, actor: 'str | None' = None, description: 'str | None' = None, tags: 'Sequence[str]' = (), metadata: 'dict[str, Any] | None' = None) -> 'PromptRecord'`

Create a prompt slot. ``type`` is ``text`` or ``chat``; ``metadata`` is validated against ``metadata_model``
when set.

#### `PromptRegistry.create_tables(self) -> 'None'`

Create the schema without Alembic (fine for tests and small apps).

#### `PromptRegistry.create_version(self, name: 'str', template: 'str | list[dict[str, Any]]', *, format: 'str' = 'python', message: 'str', actor: 'str | None' = None, locale: 'str | None' = None, config: 'dict[str, Any] | None' = None, notes: 'dict[str, Any] | None' = None) -> 'VersionRecord'`

Save an immutable version and move ``latest``. ``config=None`` keeps the previous version's config;
``notes`` is free-form JSON. The returned record carries ``warning`` when a locale variant's variables
differ from the default locale's production version.

#### `PromptRegistry.define(self, name: 'str', *, variables: 'type[V] | None' = None, config: 'type[C] | None' = None, metadata: 'type[M] | None' = None) -> 'PromptAccessor[V, C, M]'`

A typed accessor: ``accessor.get()`` returns ``Prompt[V, C, M]``.

#### `PromptRegistry.diff(self, name: 'str', a: 'int', b: 'int', locale: 'str | None' = None) -> 'str'`

Unified diff of format, template and config between versions ``a`` and ``b``.

#### `PromptRegistry.export(self, names: 'Sequence[str] | None' = None) -> 'dict[str, Any]'`

Prompts, versions and labels as plain data (JSON/YAML friendly), optionally only ``names``.

#### `PromptRegistry.get(self, name: 'str', *, label: 'str | None' = None, locale: 'str | None' = None, default: 'str | list[Message] | list[dict[str, Any]] | None' = None, ttl: 'float | None' = None, default_format: 'str | None' = None) -> 'Prompt[BaseModel, Any, Any]'`

Resolve a prompt handle. Cache hit: no I/O. Miss: one indexed query.

#### `PromptRegistry.get_prompt(self, name: 'str') -> 'PromptRecord'`

The prompt record (name, type, tags, metadata, archived_at, timestamps).

#### `PromptRegistry.health(self) -> 'dict[str, Any]'`

Database reachability plus cache statistics (size, hits, misses, hit ratio).

#### `PromptRegistry.history(self, name: 'str', locale: 'str | None' = None) -> 'list[VersionRecord]'`

Versions of a prompt, newest first, optionally for one locale.

#### `PromptRegistry.import_(self, data: 'dict[str, Any]', *, actor: 'str | None' = None, set_labels: 'bool' = True) -> 'dict[str, int]'`

Create missing prompts and versions from an export (versions matched by checksum); set labels unless
``set_labels=False``.

#### `PromptRegistry.import_prompts(self, data: 'dict[str, Any]', *, actor: 'str | None' = None, set_labels: 'bool' = True) -> 'dict[str, int]'`

Create missing prompts and versions from an export (versions matched by checksum); set labels unless
``set_labels=False``.

#### `PromptRegistry.label_history(self, name: 'str', label: 'str', locale: 'str | None' = None) -> 'list[dict[str, Any]]'`

Moves of one label, newest first, with actor, reason and change request.

#### `PromptRegistry.labels(self, name: 'str', locale: 'str | None' = None) -> 'list[LabelRecord]'`

Every label of a prompt (all locales, or one), with the version each points to.

#### `PromptRegistry.list_change_requests(self, name: 'str | None' = None, status: 'str | None' = None) -> 'list[ChangeRequestRecord]'`

Change requests, newest first, optionally for one prompt and/or one status.

#### `PromptRegistry.list_prompts(self, *, q: 'str | None' = None, tag: 'str | None' = None, metadata: 'dict[str, Any] | None' = None, include_archived: 'bool' = False) -> 'list[PromptRecord]'`

Prompts matching a name substring, a tag and/or top-level metadata values; archived ones only when asked.

#### `PromptRegistry.publish(self, name: 'str', version: 'int', label: 'str', *, actor: 'str | None' = None, locale: 'str | None' = None, expected_current: 'int | None' = None, reason: 'str | None' = None, force: 'bool' = False) -> 'LabelRecord'`

Move ``label`` to ``version``. Protected labels need an approved change request unless ``force=True``
(break-glass, recorded with ``reason``). ``expected_current`` is an optimistic lock.

#### `PromptRegistry.reject(self, cr_id: 'int', *, actor: 'str | None' = None, comment: 'str | None' = None) -> 'ChangeRequestRecord'`

Reject an open change request with an optional comment.

#### `PromptRegistry.request_change(self, name: 'str', version: 'int', label: 'str', *, actor: 'str | None' = None, locale: 'str | None' = None, comment: 'str | None' = None) -> 'ChangeRequestRecord'`

Open a change request to move ``label`` to ``version``.

#### `PromptRegistry.rollback(self, name: 'str', label: 'str', *, actor: 'str | None' = None, locale: 'str | None' = None, reason: 'str | None' = None) -> 'LabelRecord'`

Move ``label`` back to the version it pointed to before its last move (an undo; a second call redoes).

#### `PromptRegistry.stale_locales(self, name: 'str') -> 'list[str]'`

Locales not updated since the default locale's last production change.

#### `PromptRegistry.update_metadata(self, name: 'str', metadata: 'dict[str, Any]', *, actor: 'str | None' = None) -> 'PromptRecord'`

Replace a prompt's metadata without creating a version. Audited.

#### `PromptRegistry.update_prompt(self, name: 'str', *, actor: 'str | None' = None, description: 'str | None' = None, tags: 'Sequence[str] | None' = None) -> 'PromptRecord'`

Change description and/or tags. Audited.

#### `PromptRegistry.validate_version(self, template: 'str | list[dict[str, Any]]', format: 'str', config: 'dict[str, Any] | None', metadata: 'dict[str, Any] | None') -> 'None'`

Raise ``PromptValidationError``/``PromptRenderError`` for bad input (used by the UI).

### `PromptAccessor`

Typed accessor returned by :meth:`PromptRegistry.define`.

#### `async PromptAccessor.aget(self, *, label: 'str | None' = None, locale: 'str | None' = None, default: 'str | list[Message] | list[dict[str, Any]] | None' = None, ttl: 'float | None' = None) -> 'Prompt[V, C, M]'`

Typed async ``get()``: a ``Prompt[V, C, M]`` for this prompt name.

#### `PromptAccessor.get(self, *, label: 'str | None' = None, locale: 'str | None' = None, default: 'str | list[Message] | list[dict[str, Any]] | None' = None, ttl: 'float | None' = None) -> 'Prompt[V, C, M]'`

Resolve a prompt handle. Cache hit: no I/O. Miss: one indexed query (plus one per fragment).

## Handles and records

### `Prompt`

Immutable, resolved prompt handle returned by ``get()`` / ``aget()``.

| Field | Type |
| --- | --- |
| `name` | `str` |
| `version` | `int` |
| `label` | `str` |
| `locale` | `str` |
| `requested_locale` | `str` |
| `type` | `PromptType` |
| `format` | `PromptFormat` |
| `template` | `str | list[Message]` |
| `config` | `C` |
| `metadata` | `M` |
| `variables` | `tuple[str, ...]` |
| `is_fallback` | `bool` |
| `checksum` | `str` |
| `fragments` | `tuple[FragmentRef, ...]` |

#### `Prompt.compile(self, variables: 'V | None' = None, /, **kwargs: 'Any') -> 'str | list[Message]'`

Render the template. Pass a variables model instance or keyword arguments.

#### `Prompt.compile_messages(self, variables: 'V | None' = None, /, **kwargs: 'Any') -> 'list[Message]'`

``compile()`` for a ``chat`` prompt, typed as ``list[Message]``.

#### `Prompt.compile_text(self, variables: 'V | None' = None, /, **kwargs: 'Any') -> 'str'`

``compile()`` for a ``text`` prompt, typed as ``str``.

#### `Prompt.trace_attributes(self) -> 'dict[str, str | int | bool]'`

OpenTelemetry-ready span attributes.

#### `Prompt.traced(self) -> 'Iterator[None]'`

Record this prompt on the current OpenTelemetry span and carry it as baggage.

Inside the block the current span gets :meth:`trace_attributes`, and the same keys are set
as baggage so an OpenTelemetry ``BaggageSpanProcessor`` (or your own processor) can copy
them onto every child span, such as the LLM call. A no-op when OpenTelemetry is absent.

### `FragmentRef`

A fragment that was spliced into a handle, and exactly which version of it.

| Field | Type |
| --- | --- |
| `name` | `str` |
| `locale` | `str` |
| `version` | `int` |
| `label` | `str` |
| `checksum` | `str` |

### `PromptConfig`

Default typed model settings. Extra keys are kept.

| Field | Type | Default |
| --- | --- | --- |
| `model` | `str | None` | None |
| `temperature` | `float | None` | None |
| `max_tokens` | `int | None` | None |
| `tools` | `list[dict[str, Any]] | None` | None |
| `response_format` | `dict[str, Any] | None` | None |

### `Message`

One chat message of a ``chat`` prompt.

| Field | Type | Default |
| --- | --- | --- |
| `role` | `str` | required |
| `content` | `str` | required |

### `Principal`

Who is acting. The host app builds one from its own auth.

| Field | Type | Default |
| --- | --- | --- |
| `id` | `str` | required |
| `name` | `str` | '' |
| `permissions` | `frozenset` | frozenset() |

#### `Principal.can(self, permission: 'str') -> 'bool'`

True if the principal holds ``permission`` or ``prompts:admin``.

### `PromptRecord`

PromptRecord(id: 'int', name: 'str', type: 'PromptType', description: 'str | None', tags: 'tuple[str, ...]', metadata: 'dict[str, Any]', archived_at: 'datetime | None', created_at: 'datetime', updated_at: 'datetime')

| Field | Type |
| --- | --- |
| `id` | `int` |
| `name` | `str` |
| `type` | `PromptType` |
| `description` | `str | None` |
| `tags` | `tuple[str, ...]` |
| `metadata` | `dict[str, Any]` |
| `archived_at` | `datetime | None` |
| `created_at` | `datetime` |
| `updated_at` | `datetime` |

### `VersionRecord`

VersionRecord(id: 'int', prompt_id: 'int', locale: 'str', version: 'int', format: 'PromptFormat', template: 'str | list[dict[str, Any]]', config: 'dict[str, Any]', variables: 'tuple[str, ...]', checksum: 'str', message: 'str', created_by: 'str', created_at: 'datetime', notes: 'dict[str, Any] | None' = None, warning: 'str | None' = None)

| Field | Type |
| --- | --- |
| `id` | `int` |
| `prompt_id` | `int` |
| `locale` | `str` |
| `version` | `int` |
| `format` | `PromptFormat` |
| `template` | `str | list[dict[str, Any]]` |
| `config` | `dict[str, Any]` |
| `variables` | `tuple[str, ...]` |
| `checksum` | `str` |
| `message` | `str` |
| `created_by` | `str` |
| `created_at` | `datetime` |
| `notes` | `dict[str, Any] | None` |
| `warning` | `str | None` |

### `LabelRecord`

LabelRecord(id: 'int', prompt_id: 'int', locale: 'str', label: 'str', version_id: 'int', version: 'int', updated_by: 'str', updated_at: 'datetime', lock_version: 'int')

| Field | Type |
| --- | --- |
| `id` | `int` |
| `prompt_id` | `int` |
| `locale` | `str` |
| `label` | `str` |
| `version_id` | `int` |
| `version` | `int` |
| `updated_by` | `str` |
| `updated_at` | `datetime` |
| `lock_version` | `int` |

### `ChangeRequestRecord`

ChangeRequestRecord(id: 'int', prompt_id: 'int', name: 'str', locale: 'str', version_id: 'int', version: 'int', target_label: 'str', status: "Literal['open', 'approved', 'rejected', 'published']", author: 'str', reviewer: 'str | None', comment: 'str | None', created_at: 'datetime', decided_at: 'datetime | None')

| Field | Type |
| --- | --- |
| `id` | `int` |
| `prompt_id` | `int` |
| `name` | `str` |
| `locale` | `str` |
| `version_id` | `int` |
| `version` | `int` |
| `target_label` | `str` |
| `status` | `Literal['open', 'approved', 'rejected', 'published']` |
| `author` | `str` |
| `reviewer` | `str | None` |
| `comment` | `str | None` |
| `created_at` | `datetime` |
| `decided_at` | `datetime | None` |

### `AuditRecord`

AuditRecord(id: 'int', at: 'datetime', actor: 'str', action: 'str', target_type: 'str', target_id: 'str', before: 'dict[str, Any] | None', after: 'dict[str, Any] | None', reason: 'str | None')

| Field | Type |
| --- | --- |
| `id` | `int` |
| `at` | `datetime` |
| `actor` | `str` |
| `action` | `str` |
| `target_type` | `str` |
| `target_id` | `str` |
| `before` | `dict[str, Any] | None` |
| `after` | `dict[str, Any] | None` |
| `reason` | `str | None` |

## Errors

All inherit from `PromptPivotError`.

- `PromptPivotError` (Exception): Base class for every promptpivot error.
- `PromptNotFound` (PromptPivotError, LookupError): No prompt, version or label matches the request.
- `PromptRenderError` (PromptPivotError, ValueError): A template could not be rendered (missing variable, bad syntax, unsafe field).
- `PromptValidationError` (PromptPivotError, ValueError): Variables, config or metadata failed validation against their model.
- `PromptStoreUnavailable` (PromptPivotError, RuntimeError): The database could not be reached and nothing cached or default could be served.
- `PromptConflict` (PromptPivotError, RuntimeError): An optimistic lock failed: another writer moved the label first.
- `PromptPolicyError` (PromptPivotError, PermissionError): A rule blocked the action: missing approval, same author/approver, permission.

## FastAPI

### promptpivot.fastapi

#### `fastapi.admin_router(registry: 'PromptRegistry', *, principal: 'PrincipalDep', include_in_schema: 'bool' = True, ui: 'bool' = True, tags: 'Sequence[str] | None' = None) -> 'APIRouter'`

Build the admin router. Mount it with ``app.include_router(r, prefix="/admin/prompts")``.

``principal`` is a FastAPI dependency (sync or async) returning the acting
:class:`Principal`; permission checks use its ``permissions`` set.

#### `fastapi.dev_principal() -> 'Principal'`

Local-development principal with every permission.

Refuses to run unless the environment variable ``PROMPTPIVOT_DEV_UI=1`` is set, so it cannot be
deployed by accident. Never use it behind a public address.

## Migrations

### promptpivot.migrations

#### `migrations.upgrade(engine: 'Engine | AsyncEngine', prefix: 'str' = 'promptpivot_', revision: 'str' = 'head') -> 'str'`

Migrate the schema to ``revision`` with a sync or async engine.

#### `async migrations.aupgrade(engine: 'AsyncEngine', prefix: 'str' = 'promptpivot_', revision: 'str' = 'head') -> 'str'`

Async form of :func:`upgrade` for use inside a running event loop (e.g. FastAPI startup).

#### `migrations.upgrade_sync(connection: 'Connection', prefix: 'str' = 'promptpivot_', revision: 'str' = 'head') -> 'str'`

Run migrations on an open sync connection. Returns ``alembic`` or ``create_all``.

## Templating helpers

### promptpivot.templating

#### `templating.detect_variables(template: 'Any', fmt: 'str') -> 'tuple[str, ...]'`

Return the variable names a template uses, in first-seen order.

#### `templating.fragment_refs(template: 'Any') -> 'list[tuple[str, str | None]]'`

Fragment references in a template, in first-seen order: ``{> name}``, ``{> name@label}``,
``{> name@v3}`` -> ``(name, pin)`` where ``pin`` is None, a label, or ``"v3"``.

#### `templating.guess_format(template: 'Any') -> 'str'`

``jinja`` when the template contains Jinja tags or expressions, else ``python``.

#### `templating.build_renderer(template: 'Any', fmt: 'str') -> 'Renderer'`

Compile ``template`` into a renderer. Chat templates render each message's content.

## CLI

```
prompt-pivot [--url URL] [--prefix PREFIX] [--actor ACTOR] <command>
  migrate                      create or upgrade the schema
  list [-q TEXT]               prompts and their labels
  export [-o FILE] [NAME ...]  JSON (.json) or YAML (.yaml, needs prompt-pivot[yaml]); stdout without -o
  import FILE [--no-labels]    create missing prompts/versions; set labels unless --no-labels
  publish NAME VERSION LABEL [--locale L] [--reason R] [--force]
  rollback NAME LABEL [--locale L] [--reason R]
  docs                         print the agent guide (how to use the library correctly)
```

`--url` defaults to `PROMPTPIVOT_DATABASE_URL`; `--prefix` to `PROMPTPIVOT_TABLE_PREFIX`.
