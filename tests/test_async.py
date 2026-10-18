from __future__ import annotations

import asyncio

import pytest

from promptpivot import PromptNotFound, PromptRegistry, PromptStoreUnavailable


async def aseed(reg: PromptRegistry) -> None:
    await reg.acreate_prompt("support/agent", "chat", actor="ann", metadata={"owner": "cx"})
    await reg.acreate_version(
        "support/agent", [{"role": "user", "content": "Hi {{ name }}"}], format="jinja", message="init", actor="ann"
    )
    await reg.apublish("support/agent", 1, "staging", actor="ann")
    cr = await reg.arequest_change("support/agent", 1, "production", actor="ann")
    await reg.aapprove(cr.id, actor="bob")
    await reg.apublish("support/agent", 1, "production", actor="bob")


async def test_async_flow(aregistry: PromptRegistry):
    await aseed(aregistry)
    p = await aregistry.aget("support/agent")
    assert p.version == 1 and p.compile(name="A")[0].content == "Hi A"
    assert (await aregistry.ahealth())["database"] == "ok"
    assert len(await aregistry.ahistory("support/agent")) == 1
    assert (await aregistry.alabels("support/agent"))[0].label in ("latest", "production", "staging")
    await aregistry.acreate_version(
        "support/agent", [{"role": "user", "content": "v2"}], format="jinja", message="v2", actor="ann"
    )
    await aregistry.apublish("support/agent", 2, "staging", actor="ann", expected_current=1)
    assert (await aregistry.aget("support/agent", label="staging")).version == 2
    assert (await aregistry.arollback("support/agent", "staging", actor="ann")).version == 1
    assert "v2" in await aregistry.adiff("support/agent", 1, 2)
    await aregistry.aupdate_metadata("support/agent", {"owner": "x"}, actor="ann")
    await aregistry.aupdate_prompt("support/agent", actor="ann", tags=["t"])
    assert (await aregistry.aget_prompt("support/agent")).tags == ("t",)
    assert (await aregistry.alist_change_requests())[0].status == "published"
    cr = await aregistry.arequest_change("support/agent", 2, "production", actor="ann")
    assert (await aregistry.areject(cr.id, actor="bob")).status == "rejected"
    assert len(await aregistry.aaudit(limit=5)) == 5
    assert [h["to_version_id"] for h in await aregistry.alabel_history("support/agent", "staging")] == [1, 2, 1]
    data = await aregistry.aexport()
    data["prompts"][0]["name"] = "c/a"
    assert (await aregistry.aimport_prompts(data, actor="i"))["prompts"] == 1
    await aregistry.aarchive("c/a", actor="a")
    assert [p.name for p in await aregistry.alist_prompts()] == ["support/agent"]
    with pytest.raises(PromptNotFound):
        await aregistry.aget("c/a")
    assert (await aregistry.aget("c/a", default="d")).is_fallback


async def test_async_single_flight_and_default(aregistry: PromptRegistry):
    await aseed(aregistry)
    calls = 0
    real = aregistry.store.resolve

    def counted(conn, *a, **k):
        nonlocal calls
        calls += 1
        return real(conn, *a, **k)

    aregistry.store.resolve = counted  # type: ignore[method-assign]
    res = await asyncio.gather(*[aregistry.aget("support/agent") for _ in range(10)])
    assert {p.version for p in res} == {1} and calls == 1
    with pytest.raises(PromptNotFound):
        await aregistry.aget("nope")
    assert (await aregistry.aget("nope", default="x")).compile() == "x"


async def test_sync_api_on_async_engine(aregistry: PromptRegistry):
    await aseed(aregistry)
    with pytest.raises(RuntimeError):  # from inside the loop: must use the async form
        aregistry.get("support/agent", ttl=0)
    # from a worker thread while the loop runs (e.g. a sync FastAPI route): works
    assert await asyncio.to_thread(lambda: aregistry.get("support/agent").version) == 1
    assert await asyncio.to_thread(lambda: aregistry.publish("support/agent", 1, "staging", actor="t").version) == 1
    assert await asyncio.to_thread(lambda: aregistry.get("support/agent").version) == 1  # cache hit


async def test_async_store_unavailable(aregistry: PromptRegistry, monkeypatch: pytest.MonkeyPatch):
    from sqlalchemy.exc import OperationalError

    def boom(*a, **k):
        raise OperationalError("x", {}, Exception("down"))

    monkeypatch.setattr(aregistry.store, "resolve", boom)
    with pytest.raises(PromptStoreUnavailable):
        await aregistry.aget("support/agent")
    monkeypatch.setattr(aregistry.store, "health", boom)
    assert (await aregistry.ahealth())["database"] == "unavailable"
