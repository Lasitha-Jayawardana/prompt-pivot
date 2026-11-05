---
name: prompt-pivot
description: Use when writing or changing Python code that reads, defines or manages LLM prompts with the prompt-pivot library (import promptpivot: PromptRegistry, prompts.get/aget, define, admin_router, labels, locales, fragments, change requests). Gives the sync/async forms, template brace rules, publish and approval flow, permissions and error handling for the installed version.
license: Apache-2.0
metadata:
  version: "0.2.1"
  source: https://github.com/Lasitha-Jayawardana/prompt-pivot
---

# prompt-pivot: guide for coding agents and developers

Read this before writing code that uses `promptpivot`. It is short on purpose and states the rules
that are easy to get wrong. Print the copy that matches the installed version with `prompt-pivot docs`
or `python -c "import promptpivot; print(promptpivot.agent_guide())"`. If you are reading this on
GitHub, features may be newer than the installed package: check `promptpivot.__version__` against the
changelog before using them. `prompt-pivot skill` writes this guide as an Agent Skill (`SKILL.md`)
into the project so it loads automatically next time.

## What the library is

A Python library (PyPI `prompt-pivot`, import `promptpivot`) that stores versioned LLM prompts in the
host application's own PostgreSQL, MySQL or SQLite database and serves them at runtime through a
cached registry. Prompts are edited, reviewed, published and rolled back in a built-in FastAPI admin
UI. The library never calls an LLM.

Core objects: `PromptRegistry` (one per app), `Prompt` (an immutable handle returned by reads),
labels (`production`, `staging`, `latest`, custom), locales, change requests, fragments.

## Setup (once per app)

```python
from fastapi import Depends, FastAPI
from sqlalchemy.ext.asyncio import create_async_engine
from prompt-pivot import PromptRegistry, Principal
from promptpivot.fastapi import admin_router

engine = create_async_engine(DATABASE_URL)  # sync Engine works too
prompts = PromptRegistry(engine, environment="production")  # module-level singleton


async def principal(user=Depends(get_current_user)) -> Principal:
    return Principal(id=user.id, name=user.email, permissions=frozenset(map_roles(user.roles)))


app = FastAPI()
app.include_router(admin_router(prompts, principal=principal), prefix="/admin/prompts")
```

- Create the schema with `prompt-pivot migrate --url ...` (CLI) or `await promptpivot.migrations.aupgrade(engine)`
  / `promptpivot.migrations.upgrade(engine)`. Do not call `create_all` yourself in production.
- Local development without auth: `principal=dev_principal` from `promptpivot.fastapi`, with the
  environment variable `PROMPTPIVOT_DEV_UI=1`. Never ship that.
- Tests: `PromptRegistry.in_memory()` gives a registry on a private SQLite database with tables.

## Reading prompts (the common case)

```python
p = await prompts.aget("support/agent", locale=user.locale, default=FALLBACK_TEXT)
messages = p.compile_messages(customer_name=user.name, question=q)  # chat prompt -> list[Message]
text = p.compile_text(name=...)  # text prompt -> str
with p.traced():  # prompt.* on the current span + baggage
    response = await llm.chat(
        model=p.config.model, temperature=p.config.temperature, messages=[m.model_dump() for m in messages]
    )
```

On Pydantic 1.10 (supported for legacy apps) use `m.dict()` instead of `m.model_dump()`; check with
`pydantic.VERSION`. Everything else in this guide is the same on both.

Rules:

1. In `async def` code use `aget` / `a*` methods. In sync code (scripts, Celery tasks, sync routes)
   use `get` / plain methods. Calling a sync method from inside a running event loop raises
   `RuntimeError`; with an `AsyncEngine` the sync forms work from worker threads and scripts.
2. Reads resolve a **label**, never a version number. The default label is the registry's
   `environment`. Pass `label="staging"` or a custom label only when the code really wants that.
3. Give business-critical prompts a `default=` (string, or list of role/content dicts) so a brand-new
   worker can start during a database outage. The handle then has `is_fallback=True`.
4. Use `compile_text()` for text prompts and `compile_messages()` for chat prompts; they are typed and
   fail loudly on the wrong prompt type. `compile()` returns the union type.
5. Missing variables raise `PromptRenderError`. Do not catch and ignore it; the prompt is broken.
6. For prompts used from more than one place, declare them once:

```python
class SupportVars(BaseModel):
    customer_name: str
    question: str


support_agent = prompts.define("support/agent", variables=SupportVars)  # typed accessor, module level
p = await support_agent.aget()
messages = p.compile_messages(SupportVars(customer_name="A", question="q"))  # validated
```

7. Handles are immutable and cached per process (`cache_ttl`, default 60 s). Do not cache them
   yourself and do not hold one across requests; call `aget` per request.

## Templates

- `python` format: only `{name}` or `{name:spec}` with a plain identifier is a variable. Every other
  brace, including JSON examples such as `{"city": "Paris"}`, is kept as text. `{{name}}` prints a
  literal `{name}`.
- `jinja` format: `{{ name }}`, `{% if %}`, `{% for %}`; sandboxed, strict (missing variables raise).
- Fragments: `{> common/safety}` includes a `text` prompt; `{> common/safety@staging}` pins a label,
  `{> common/safety@v3}` pins a version. Fragments are inserted as text and rendered with the
  parent's format. `handle.fragments` records the versions used.
- `default=` templates: the format is guessed from Jinja tags; pass `default_format="python"` or
  `"jinja"` to be explicit.

## Writing prompts (rare from code)

Prompts are normally created and edited in the admin UI, or moved between environments with
`prompt-pivot export` / `prompt-pivot import` (also the UI's Import/Export pages). From code:

```python
prompts.create_prompt("support/agent", "chat", tags=["support"], metadata={"owner": "cx"})
rec = prompts.create_version("support/agent", [{"role": "user", "content": "{question}"}], message="first")
prompts.publish("support/agent", rec.version, "staging")
```

Rules:

- Every write takes `actor=` (defaults to the registry's `default_actor`, `"system"`). Pass the real
  user id when acting for a person; it goes into the audit log.
- `create_version(config=None)` keeps the previous version's config; pass `config={}` to clear it.
- Protected labels (`production` by default) cannot be published directly: `request_change(...)`,
  then `approve(cr_id, actor=<someone else>)`, then `publish(...)`. `publish(..., force=True,
  reason=...)` is break-glass for incidents only and is highlighted in the audit log.
- `rollback(name, label)` undoes the last move of a label; calling it twice redoes the move.
- Do not write seeding code that runs on every startup. Seed once with `import_prompts` / the CLI.

## Permissions (for the `Principal` the host builds)

`prompts:read`, `prompts:edit`, `prompts:publish:<label>` (for example `prompts:publish:staging`),
`prompts:approve`, `prompts:admin` (everything, plus archive, audit log, import/export, break-glass).

## Errors

| Error | Meaning | What to do |
| --- | --- | --- |
| `PromptNotFound` | no prompt / version / label matches | check the name and that the label is published; or pass `default=` |
| `PromptRenderError` | missing variable, bad template, fragment cycle | fix the template or the call site |
| `PromptValidationError` | variables/config/metadata fail their model; bad input | fix the data |
| `PromptStoreUnavailable` | database down, nothing cached, no `default=` | add `default=` to critical prompts; check the database |
| `PromptConflict` | concurrent label move (optimistic lock) or duplicate prompt | re-read and retry |
| `PromptPolicyError` | approval or author/approver rule blocked the action | follow the change-request flow |

All inherit from `PromptPivotError`.

## Do not

- Do not import or call `promptpivot.store` or `registry._run` directly; use the registry methods.
- Do not read version numbers in application code; read labels.
- Do not put `force=True` in normal code paths.
- Do not render missing variables as empty strings; let `PromptRenderError` surface.
- Do not mount `admin_router` without a real `principal` outside local development.

## More

In the repository https://github.com/Lasitha-Jayawardana/prompt-pivot: README (quickstart,
settings, security), `docs/guide.md` (every feature with code, UI and use cases), `docs/reference.md`
(generated API reference), `skills/prompt-pivot/SKILL.md` (this guide as an Agent Skill). In a running
app: `GET <prefix>/openapi.json` for the REST API.
