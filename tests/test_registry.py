from __future__ import annotations

import threading
import time

import pytest
from pydantic import BaseModel
from sqlalchemy.exc import OperationalError

from promptpivot import (
    PromptConflict,
    PromptNotFound,
    PromptPolicyError,
    PromptRegistry,
    PromptRenderError,
    PromptStoreUnavailable,
    PromptValidationError,
)
from tests.conftest import seed


def test_create_version_publish_get(registry: PromptRegistry):
    seed(registry)
    p = registry.get("support/agent")
    assert (p.version, p.label, p.locale, p.requested_locale, p.is_fallback) == (1, "production", "en", "en", False)
    assert p.compile(customer_name="Alice", plan="Pro") == "Help Alice on the Pro plan."
    assert p.config.model == "m1" and p.config.temperature == 0.1
    assert p.metadata == {"owner": "cx"} and p.variables == ("customer_name", "plan")
    assert p.trace_attributes()["prompt.version"] == 1
    with pytest.raises(PromptRenderError):
        p.compile(customer_name="x")
    assert registry.get("support/agent", label="latest").version == 1
    with pytest.raises(PromptNotFound):
        registry.get("support/agent", label="canary")
    with pytest.raises(PromptNotFound):
        registry.get("nope")


def test_validation_rules(registry: PromptRegistry):
    with pytest.raises(PromptValidationError):
        registry.create_prompt("bad name", actor="a")
    with pytest.raises(PromptValidationError):
        registry.create_prompt("x", "image", actor="a")
    registry.create_prompt("x", "chat", actor="a")
    with pytest.raises(PromptConflict):
        registry.create_prompt("x", actor="a")
    with pytest.raises(PromptValidationError):
        registry.create_version("x", "not a list", message="m", actor="a")
    with pytest.raises(PromptValidationError):
        registry.create_version("x", [{"role": "u", "content": "hi"}], format="yaml", message="m", actor="a")
    with pytest.raises(PromptValidationError):
        registry.create_version(
            "x", [{"role": "u", "content": "hi"}], message="m", actor="a", config={"temperature": "hot"}
        )
    with pytest.raises(PromptRenderError):
        registry.create_version("x", [{"role": "u", "content": "{a.b}"}], message="m", actor="a")


def test_protected_label_review_flow(registry: PromptRegistry):
    seed(registry)
    registry.create_version("support/agent", "v2 {customer_name}", message="v2", actor="ann")
    with pytest.raises(PromptPolicyError):
        registry.publish("support/agent", 2, "production", actor="ann")
    with pytest.raises(PromptPolicyError):
        registry.publish("support/agent", 2, "latest", actor="ann")
    cr = registry.request_change("support/agent", 2, "production", actor="ann", comment="please")
    assert cr.status == "open" and cr.version == 2
    with pytest.raises(PromptPolicyError):
        registry.approve(cr.id, actor="ann")  # same author
    cr = registry.approve(cr.id, actor="bob")
    assert cr.status == "approved" and cr.reviewer == "bob"
    with pytest.raises(PromptPolicyError):
        registry.approve(cr.id, actor="bob")  # already decided
    lb = registry.publish("support/agent", 2, "production", actor="bob")
    assert lb.version == 2
    assert registry.list_change_requests("support/agent")[0].status == "published"
    assert registry.get("support/agent").version == 2  # publishing worker sees it at once
    cr2 = registry.request_change("support/agent", 1, "production", actor="ann")
    assert registry.reject(cr2.id, actor="bob", comment="no").status == "rejected"
    assert len(registry.list_change_requests(status="rejected")) == 1


def test_no_distinct_approver_option(registry: PromptRegistry):
    registry.store.require_distinct_approver = False
    seed(registry)
    cr = registry.request_change("support/agent", 1, "production", actor="ann")
    assert registry.approve(cr.id, actor="ann").status == "approved"


def test_optimistic_lock_and_rollback(registry: PromptRegistry):
    seed(registry)
    registry.create_version("support/agent", "v2", message="v2", actor="ann")
    registry.publish("support/agent", 2, "staging", actor="ann", expected_current=1)
    with pytest.raises(PromptConflict):
        registry.publish("support/agent", 1, "staging", actor="ann", expected_current=1)
    with pytest.raises(PromptConflict):
        registry.publish("support/agent", 1, "canary", actor="ann", expected_current=1)  # not set yet
    lb = registry.rollback("support/agent", "staging", actor="ann")
    assert lb.version == 1
    assert registry.get("support/agent", label="staging").version == 1
    hist = registry.label_history("support/agent", "staging")
    assert [h["to_version_id"] for h in hist] == [1, 2, 1]
    with pytest.raises(PromptNotFound):
        registry.rollback("support/agent", "canary", actor="ann")
    registry.publish("support/agent", 2, "canary", actor="ann")
    with pytest.raises(PromptNotFound):
        registry.rollback("support/agent", "canary", actor="ann")  # no previous
    with pytest.raises(PromptNotFound):
        registry.rollback("support/agent", "production", actor="ops")  # seeded by force: no previous version


def test_locale_fallback_and_warning(registry: PromptRegistry):
    seed(registry)
    rec = registry.create_version(
        "support/agent", "Bonjour {customer_name} ({plan})", message="fr", actor="ann", locale="fr"
    )
    assert rec.warning is None
    rec = registry.create_version("support/agent", "Hallo {customer_name}", message="de", actor="ann", locale="de")
    assert rec.warning and "plan" in rec.warning
    registry.publish("support/agent", 1, "production", actor="ann", locale="fr", force=True)
    p = registry.get("support/agent", locale="fr-CA")
    assert (p.locale, p.requested_locale) == ("fr", "fr-CA")
    assert registry.get("support/agent", locale="fr").locale == "fr"
    assert registry.get("support/agent", locale="de").locale == "en"  # de has no production label
    assert registry.get("support/agent", locale="pt-BR").locale == "en"
    assert sorted({v.locale for v in registry.history("support/agent")}) == ["de", "en", "fr"]
    assert len(registry.history("support/agent", "fr")) == 1


def test_typed_define(registry: PromptRegistry):
    seed(registry)

    class Vars(BaseModel):
        customer_name: str
        plan: str

    class Cfg(BaseModel):
        model: str
        temperature: float = 0

    class Meta(BaseModel):
        owner: str
        team: str | None = None

    acc = registry.define("support/agent", variables=Vars, config=Cfg, metadata=Meta)
    p = acc.get()
    assert isinstance(p.config, Cfg) and p.config.model == "m1"
    assert isinstance(p.metadata, Meta) and p.metadata.owner == "cx"
    assert p.compile(Vars(customer_name="A", plan="B")) == "Help A on the B plan."
    assert p.compile(customer_name="A", plan="B") == "Help A on the B plan."
    with pytest.raises(PromptValidationError):
        p.compile(customer_name="A")
    with pytest.raises(TypeError):
        p.compile(Vars(customer_name="A", plan="B"), plan="C")
    # typed and untyped handles are cached separately
    assert type(registry.get("support/agent").config).__name__ == "PromptConfig"
    # metadata that fails the model is a typed error
    registry.update_metadata("support/agent", {"team": "x"}, actor="ann")
    with pytest.raises(PromptValidationError):
        acc.get()
    registry.metadata_model = Meta
    with pytest.raises(PromptValidationError):
        registry.update_metadata("support/agent", {"nope": 1}, actor="ann")


def test_default_fallback_and_chat_default(registry: PromptRegistry):
    p = registry.get("missing", default="Hello {n}!")
    assert p.is_fallback and p.version == 0 and p.compile(n=1) == "Hello 1!"
    p = registry.get("missing", default=[{"role": "user", "content": "{q}"}])
    assert p.type == "chat" and p.compile(q="x")[0].content == "x"


def test_cache_ttl_and_invalidate(registry: PromptRegistry):
    seed(registry)
    assert registry.get("support/agent").version == 1
    # direct store writes bypass this registry's own invalidation
    registry._run(registry.store.create_version, "support/agent", "v2", format="python", message="m", actor="a")
    registry._run(registry.store.publish, "support/agent", 2, "staging", actor="a")
    assert registry.get("support/agent", label="staging").version == 2  # first read, not cached before
    registry._run(registry.store.publish, "support/agent", 1, "staging", actor="a")
    assert registry.get("support/agent", label="staging").version == 2  # cached
    assert registry.get("support/agent", label="staging", ttl=0).version == 1  # bypass
    assert registry.get("support/agent", label="staging").version == 2  # still cached
    registry.cache.invalidate("support/agent")
    assert registry.get("support/agent", label="staging").version == 1
    stats = registry.health()["cache"]
    assert stats["hits"] >= 2 and stats["size"] >= 1
    registry.cache_ttl = 0
    registry._run(registry.store.publish, "support/agent", 2, "staging", actor="a")
    assert registry.get("support/agent", label="staging").version == 2


def test_lru_bound(registry: PromptRegistry):
    registry.cache.max_entries = 2
    for i in range(3):
        registry.create_prompt(f"p{i}", actor="a")
        registry.create_version(f"p{i}", "x", message="m", actor="a")
        registry.publish(f"p{i}", 1, "staging", actor="a")
        registry.get(f"p{i}", label="staging")
    assert len(registry.cache) == 2


def test_stale_on_db_error(registry: PromptRegistry, monkeypatch: pytest.MonkeyPatch):
    seed(registry)
    registry.get("support/agent")

    def boom(*a, **k):
        raise OperationalError("select", {}, Exception("db down"))

    monkeypatch.setattr(registry.store, "resolve", boom)
    for e in registry.cache._data.values():
        e.expires_at = 0  # expire everything
    p = registry.get("support/agent")
    assert p.is_fallback and p.version == 1
    assert registry.get("support/agent").is_fallback  # re-armed briefly, no second query storm
    with pytest.raises(PromptStoreUnavailable):
        registry.get("support/agent", label="staging")
    assert registry.get("support/agent", label="staging", default="d").is_fallback
    registry.max_stale = 0
    for e in registry.cache._data.values():
        e.expires_at = 0
        e.loaded_at = 0
    with pytest.raises(PromptStoreUnavailable):
        registry.get("support/agent")
    assert registry.health()["database"] == "ok"
    monkeypatch.setattr(registry.store, "health", boom)
    assert registry.health()["database"] == "unavailable"


def test_single_flight_threads(registry: PromptRegistry):
    seed(registry)
    registry.cache.invalidate()
    calls = 0
    real = registry.store.resolve

    def slow(conn, *a, **k):
        nonlocal calls
        calls += 1
        time.sleep(0.05)
        return real(conn, *a, **k)

    registry.store.resolve = slow  # type: ignore[method-assign]
    out: list[int] = []
    ts = [threading.Thread(target=lambda: out.append(registry.get("support/agent").version)) for _ in range(8)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert out == [1] * 8 and calls == 1


def test_list_filter_archive_metadata(registry: PromptRegistry):
    seed(registry)
    registry.create_prompt("billing/x", actor="a", tags=["billing"], metadata={"owner": "fin"})
    assert [p.name for p in registry.list_prompts(q="bill")] == ["billing/x"]
    assert [p.name for p in registry.list_prompts(tag="support")] == ["support/agent"]
    assert [p.name for p in registry.list_prompts(metadata={"owner": "fin"})] == ["billing/x"]
    registry.update_prompt("billing/x", actor="a", description="d", tags=["b2"])
    assert registry.get_prompt("billing/x").tags == ("b2",)
    registry.archive("support/agent", actor="a")
    assert [p.name for p in registry.list_prompts()] == ["billing/x"]
    assert len(registry.list_prompts(include_archived=True)) == 2
    with pytest.raises(PromptNotFound):
        registry.get("support/agent")  # archived prompts are not served
    registry.archive("support/agent", actor="a", archived=False)
    assert registry.get("support/agent").version == 1
    actions = [a.action for a in registry.audit(target_id="support/agent")]
    assert actions[:2] == ["unarchive", "archive"]
    assert registry.audit(actor="nobody") == []


def test_diff_and_export_import_roundtrip(registry: PromptRegistry):
    seed(registry)
    registry.create_version("support/agent", "v2 {customer_name}", message="v2", actor="ann", config={"model": "m2"})
    d = registry.diff("support/agent", 1, 2)
    assert "-Help {customer_name}" in d and '+  "model": "m2"' in d
    data = registry.export()
    assert data["prompts"][0]["locales"]["en"]["labels"] == {"production": 1, "staging": 1}
    assert len(data["prompts"][0]["locales"]["en"]["versions"]) == 2
    # import into the same db is a no-op; into a renamed prompt creates everything
    assert registry.import_prompts(data, actor="imp") == {"prompts": 0, "versions": 0, "labels": 0}
    data["prompts"][0]["name"] = "copy/agent"
    assert registry.import_(data, actor="imp") == {"prompts": 1, "versions": 2, "labels": 2}  # old alias
    assert registry.get("copy/agent").compile(customer_name="A", plan="B") == "Help A on the B plan."
    assert registry.export(["copy/agent"])["prompts"][0]["name"] == "copy/agent"


def test_multi_worker_publish(tmp_path):
    """Two registries (workers) on one database: a publish by one reaches the other within the TTL."""
    from sqlalchemy import create_engine

    url = f"sqlite:///{tmp_path}/w.db"
    a = PromptRegistry(create_engine(url), cache_ttl=0.2)
    b = PromptRegistry(create_engine(url), cache_ttl=0.2)
    a.create_tables()
    seed(a)
    assert b.get("support/agent").version == 1
    a.create_version("support/agent", "v2", message="m", actor="x")
    a.publish("support/agent", 2, "production", actor="x", force=True)
    assert a.get("support/agent").version == 2  # publisher: immediate
    assert b.get("support/agent").version == 1  # other worker: still cached
    time.sleep(0.25)
    assert b.get("support/agent").version == 2  # within TTL


def test_config_carry_over_and_message_input(registry: PromptRegistry):
    from promptpivot import Message

    registry.create_prompt("c", "chat", actor="a")
    registry.create_version("c", [Message(role="user", content="v1 {q}")], message="m", config={"model": "m1"})
    rec = registry.create_version("c", [{"role": "user", "content": "v2 {q}"}], message="m")
    assert rec.config == {"model": "m1"}  # config=None keeps the previous version's config
    assert rec.created_by == "system"  # default actor
    rec = registry.create_version("c", [{"role": "user", "content": "v3 {q}"}], message="m", config={})
    assert rec.config == {}  # explicit {} clears
    with pytest.raises(PromptRenderError):
        registry.create_version("c", [{"role": "user"}], message="m")
    registry.publish("c", 1, "staging")
    p = registry.get("c", label="staging")
    assert p.compile_messages(q="x")[0].content == "v1 x"
    with pytest.raises(PromptRenderError):
        p.compile_text(q="x")
    t = registry.get("support/agent", default="hi {n}")
    assert t.compile_text(n=1) == "hi 1"
    with pytest.raises(PromptRenderError):
        t.compile_messages(n=1)


def test_rollback_target_and_in_memory():
    reg = PromptRegistry.in_memory(default_actor="me")
    reg.create_prompt("r")
    reg.create_version("r", "a", message="m")
    reg.create_version("r", "b", message="m")
    assert reg._run(reg.store.rollback_target, "r", "staging") is None
    reg.publish("r", 1, "staging")
    assert reg._run(reg.store.rollback_target, "r", "staging") is None
    reg.publish("r", 2, "staging")
    assert reg._run(reg.store.rollback_target, "r", "staging") == 1
    reg.rollback("r", "staging")
    assert reg._run(reg.store.rollback_target, "r", "staging") == 2  # undo of the undo
    assert reg.audit(limit=1)[0].actor == "me"
