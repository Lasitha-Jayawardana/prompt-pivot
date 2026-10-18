"""Minimal host app. Run: uvicorn examples.app:app --reload  then open http://127.0.0.1:8000/admin/prompts

Uses SQLite so it runs anywhere; swap the URL for PostgreSQL or MySQL in real apps.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, Request
from sqlalchemy.ext.asyncio import create_async_engine

from promptdeck import Principal, PromptRegistry
from promptdeck.fastapi import admin_router
from promptdeck.migrations import aupgrade

DB = Path(__file__).with_name("promptdeck-demo.db")
engine = create_async_engine(f"sqlite+aiosqlite:///{DB}")
prompts = PromptRegistry(engine, environment="production", cache_ttl=30)

ROLE_PERMISSIONS = {
    "admin": {"prompts:admin"},
    "editor": {"prompts:read", "prompts:edit", "prompts:publish:staging"},
    "approver": {"prompts:read", "prompts:approve", "prompts:publish:production"},
}


async def principal(request: Request) -> Principal:
    """Demo auth: ?as=editor|approver|admin. Replace with your JWT/session dependency."""
    role = request.query_params.get("as") or request.cookies.get("role") or "admin"
    return Principal(id=role, name=role.title(), permissions=frozenset(ROLE_PERMISSIONS[role]))


app = FastAPI(title="promptdeck demo")
app.include_router(admin_router(prompts, principal=principal), prefix="/admin/prompts")


@app.on_event("startup")
async def seed() -> None:
    await aupgrade(engine)
    if not await prompts.alist_prompts():
        await prompts.acreate_prompt(
            "support/agent", "chat", actor="seed", tags=["support"], metadata={"owner": "cx-team"}
        )
        await prompts.acreate_version(
            "support/agent",
            [
                {"role": "system", "content": "You help {customer_name} on the {plan} plan."},
                {"role": "user", "content": "{question}"},
            ],
            format="python",
            message="first version",
            actor="seed",
            config={"model": "claude-sonnet-5-5", "temperature": 0.2},
        )
        await prompts.apublish("support/agent", 1, "staging", actor="seed")
        await prompts.apublish("support/agent", 1, "production", actor="seed", force=True, reason="seed")


@app.get("/answer")
async def answer(question: str, locale: str = "en") -> dict[str, object]:
    p = await prompts.aget("support/agent", locale=locale, default=[{"role": "user", "content": "{question}"}])
    messages = p.compile(customer_name="Alice", plan="Pro", question=question)
    return {
        "version": p.version,
        "locale": p.locale,
        "is_fallback": p.is_fallback,
        "model": p.config.model,
        "messages": [m.model_dump() for m in messages],
    }
