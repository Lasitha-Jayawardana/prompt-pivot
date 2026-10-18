from __future__ import annotations

import json

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from promptdeck import Principal, PromptRegistry
from promptdeck.fastapi import admin_router
from tests.conftest import seed

ROLES = {
    "admin": {"prompts:admin"},
    "editor": {"prompts:read", "prompts:edit", "prompts:publish:staging"},
    "approver": {"prompts:read", "prompts:approve", "prompts:publish:production"},
    "viewer": {"prompts:read"},
}


@pytest.fixture
def client():
    engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    reg = PromptRegistry(engine, cache_ttl=30)
    reg.create_tables()
    seed(reg)

    def principal(request: Request) -> Principal:
        role = request.headers.get("x-role", "viewer")
        return Principal(id=role, name=role, permissions=frozenset(ROLES[role]))

    app = FastAPI()
    app.include_router(admin_router(reg, principal=principal), prefix="/admin/prompts")
    with TestClient(app) as c:
        c.reg = reg  # type: ignore[attr-defined]
        yield c


def post(c: TestClient, path: str, role: str, **data: str) -> object:
    tok = c.cookies.get("promptdeck_csrf")
    return c.post(path, data={"csrf": tok, **data}, headers={"x-role": role}, follow_redirects=False)


def test_ui_pages_and_permissions(client: TestClient):
    r = client.get("/admin/prompts/", headers={"x-role": "viewer"})
    assert r.status_code == 200 and "support/agent" in r.text and client.cookies.get("promptdeck_csrf")
    assert "New prompt" not in r.text
    assert client.get("/admin/prompts/new", headers={"x-role": "viewer"}).status_code == 403
    assert client.get("/admin/prompts/new", headers={"x-role": "editor"}).status_code == 200
    r = client.get("/admin/prompts/p/support/agent", headers={"x-role": "editor"})
    assert r.status_code == 200 and "New version" in r.text and "Request production" in r.text
    assert client.get("/admin/prompts/p/support/agent?locale=fr", headers={"x-role": "editor"}).status_code == 200
    assert client.get("/admin/prompts/p/nope", headers={"x-role": "editor"}).status_code == 404
    assert client.get("/admin/prompts/audit", headers={"x-role": "editor"}).status_code == 403
    assert client.get("/admin/prompts/audit?target=support", headers={"x-role": "admin"}).status_code == 200
    assert client.get("/admin/prompts/?q=supp&tag=support", headers={"x-role": "viewer"}).status_code == 200


def test_ui_csrf(client: TestClient):
    client.get("/admin/prompts/", headers={"x-role": "editor"})
    r = client.post(
        "/admin/prompts/p/support/agent/versions",
        data={"csrf": "nope", "template": "x", "message": "m"},
        headers={"x-role": "editor"},
    )
    assert r.status_code == 403
    r = client.post("/admin/prompts/p/support/agent/versions", json={"template": "x"}, headers={"x-role": "editor"})
    assert r.status_code == 415


def test_ui_full_flow(client: TestClient):
    client.get("/admin/prompts/", headers={"x-role": "editor"})
    r = post(
        client, "/admin/prompts/new", "editor", name="chat/x", type="chat", tags="a, b", description="", metadata="{}"
    )
    assert r.status_code == 303 and "chat/x" in r.headers["location"]
    r = post(
        client,
        "/admin/prompts/p/chat/x/versions",
        "editor",
        locale="en",
        format="jinja",
        message="v1",
        template=json.dumps([{"role": "user", "content": "Hi {{ n }}"}]),
        config='{"model": "m"}',
    )
    assert r.status_code == 303 and "Saved+v1" in r.headers["location"]
    r = post(
        client,
        "/admin/prompts/p/chat/x/versions",
        "editor",
        locale="en",
        format="jinja",
        message="bad",
        template='{"role": "x"}',
        config="",
    )
    assert r.status_code == 422
    r = post(
        client,
        "/admin/prompts/p/chat/x/versions",
        "editor",
        locale="en",
        format="python",
        message="bad",
        template='[{"role": "u", "content": "x"}]',
        config="not json",
    )
    assert r.status_code == 422 and "invalid JSON" in r.text
    r = post(client, "/admin/prompts/p/chat/x/preview", "editor", version="1", locale="en", variables='{"n": "Zed"}')
    assert r.status_code == 200 and "Hi Zed" in r.text
    assert (
        post(client, "/admin/prompts/p/chat/x/publish", "editor", version="1", label="staging", locale="en").status_code
        == 303
    )
    assert (
        post(
            client, "/admin/prompts/p/chat/x/publish", "editor", version="1", label="production", locale="en"
        ).status_code
        == 403
    )
    r = post(
        client, "/admin/prompts/p/chat/x/request", "editor", version="1", label="production", locale="en", comment="c"
    )
    assert r.status_code == 303
    cr = client.reg.list_change_requests("chat/x")[0]  # type: ignore[attr-defined]
    assert post(client, f"/admin/prompts/cr/{cr.id}/approve", "editor").status_code == 403
    assert post(client, f"/admin/prompts/cr/{cr.id}/approve", "approver").status_code == 303
    r = post(client, "/admin/prompts/p/chat/x/publish", "approver", version="1", label="production", locale="en")
    assert r.status_code == 303 and "points+to+v1" in r.headers["location"]
    # force publish needs admin and a reason is recorded
    post(
        client,
        "/admin/prompts/p/chat/x/versions",
        "editor",
        locale="en",
        format="jinja",
        message="v2",
        template=json.dumps([{"role": "user", "content": "v2"}]),
        config="",
    )
    assert (
        post(
            client,
            "/admin/prompts/p/chat/x/publish",
            "approver",
            version="2",
            label="production",
            locale="en",
            force="1",
        ).status_code
        == 403
    )
    assert (
        post(
            client,
            "/admin/prompts/p/chat/x/publish",
            "admin",
            version="2",
            label="production",
            locale="en",
            force="1",
            reason="incident",
        ).status_code
        == 303
    )
    r = post(client, "/admin/prompts/p/chat/x/rollback", "approver", label="production", locale="en")
    assert r.status_code == 303 and "back+to+v1" in r.headers["location"]
    assert (
        post(client, "/admin/prompts/p/chat/x/rollback", "editor", label="production", locale="en").status_code == 403
    )
    r = client.get("/admin/prompts/p/chat/x/diff?a=1&b=2", headers={"x-role": "viewer"})
    assert r.status_code == 200 and "Hi {{ n }}" in r.text
    r = post(
        client,
        "/admin/prompts/p/chat/x/metadata",
        "editor",
        locale="en",
        description="d",
        tags="x",
        metadata='{"owner": "o"}',
    )
    assert r.status_code == 303 and client.reg.get_prompt("chat/x").metadata == {"owner": "o"}  # type: ignore[attr-defined]
    assert post(client, "/admin/prompts/p/chat/x/archive", "admin").status_code == 303
    assert post(client, "/admin/prompts/p/chat/x/archive", "admin", undo="1").status_code == 303
    r = client.get("/admin/prompts/p/chat/x", headers={"x-role": "admin"})
    assert r.status_code == 200 and "Force production" in r.text
    assert any(a.reason == "break-glass: incident" for a in client.reg.audit(target_id="chat/x"))  # type: ignore[attr-defined]


def test_api(client: TestClient):
    h = {"x-role": "editor"}
    assert client.get("/admin/prompts/api/health", headers=h).json()["database"] == "ok"
    assert client.get("/admin/prompts/api/prompts", headers={"x-role": "viewer"}).json()[0]["name"] == "support/agent"
    assert (
        client.post("/admin/prompts/api/prompts", json={"name": "x/y"}, headers={"x-role": "viewer"}).status_code == 403
    )
    assert client.post("/admin/prompts/api/prompts", json={"name": "x/y"}, headers=h).status_code == 201
    assert client.post("/admin/prompts/api/prompts", json={"name": "x/y"}, headers=h).status_code == 409
    assert client.post("/admin/prompts/api/prompts/x/y/versions", data={"template": "x"}, headers=h).status_code == 415
    r = client.post(
        "/admin/prompts/api/prompts/x/y/versions", json={"template": "Hello {n}", "message": "m"}, headers=h
    )
    assert r.status_code == 201 and r.json()["variables"] == ["n"] and r.json()["warning"] is None
    assert client.put("/admin/prompts/api/prompts/x/y/metadata", json={"metadata": {"a": 1}}, headers=h).json()[
        "metadata"
    ] == {"a": 1}
    assert (
        client.post(
            "/admin/prompts/api/prompts/x/y/publish", json={"version": 1, "label": "staging"}, headers=h
        ).json()["version"]
        == 1
    )
    assert (
        client.post(
            "/admin/prompts/api/prompts/x/y/publish", json={"version": 1, "label": "production"}, headers=h
        ).status_code
        == 403
    )
    r = client.post(
        "/admin/prompts/api/prompts/x/y/publish",
        json={"version": 1, "label": "production"},
        headers={"x-role": "approver"},
    )
    assert r.status_code == 403 and r.json()["error"] == "PromptPolicyError"
    r = client.post(
        "/admin/prompts/api/prompts/x/y/change-requests", json={"version": 1, "label": "production"}, headers=h
    )
    assert r.status_code == 201
    cr_id = r.json()["id"]
    assert client.get("/admin/prompts/api/change-requests?status=open", headers=h).json()[0]["id"] == cr_id
    assert (
        client.post(
            f"/admin/prompts/api/change-requests/{cr_id}/approve", json={}, headers={"x-role": "approver"}
        ).json()["status"]
        == "approved"
    )
    assert (
        client.post(
            "/admin/prompts/api/prompts/x/y/publish",
            json={"version": 1, "label": "production"},
            headers={"x-role": "approver"},
        ).status_code
        == 200
    )
    assert (
        client.post(
            "/admin/prompts/api/prompts/x/y/publish",
            json={"version": 1, "label": "production", "force": True},
            headers={"x-role": "approver"},
        ).status_code
        == 403
    )
    r = client.post(
        "/admin/prompts/api/prompts/x/y/change-requests", json={"version": 1, "label": "production"}, headers=h
    )
    assert (
        client.post(
            f"/admin/prompts/api/change-requests/{r.json()['id']}/reject",
            json={"comment": "no"},
            headers={"x-role": "approver"},
        ).json()["status"]
        == "rejected"
    )
    assert (
        client.post(
            "/admin/prompts/api/prompts/x/y/rollback", json={"label": "production"}, headers={"x-role": "approver"}
        ).status_code
        == 404
    )
    r = client.get("/admin/prompts/api/prompts/x/y", headers=h).json()
    assert (
        r["prompt"]["name"] == "x/y"
        and len(r["versions"]) == 1
        and {x["label"] for x in r["labels"]} == {"latest", "staging", "production"}
    )
    assert client.get("/admin/prompts/api/prompts/x/y/diff?a=1&b=1", headers=h).json()["diff"] == ""
    r = client.post("/admin/prompts/api/prompts/x/y/preview", json={"version": 1, "variables": {"n": "A"}}, headers=h)
    assert r.json() == {"rendered": "Hello A"}
    r = client.post("/admin/prompts/api/prompts/x/y/preview", json={"version": 1}, headers=h)
    assert r.status_code == 422 and r.json()["error"] == "PromptRenderError"
    assert client.post("/admin/prompts/api/prompts/x/y/preview", json={"version": 9}, headers=h).status_code == 404
    assert client.get("/admin/prompts/api/audit", headers=h).status_code == 403
    assert len(client.get("/admin/prompts/api/audit?target_id=x/y", headers={"x-role": "admin"}).json()) >= 5
    assert client.post("/admin/prompts/api/prompts/x/y/archive", json={}, headers={"x-role": "admin"}).json()[
        "archived_at"
    ]
    assert client.get("/admin/prompts/api/prompts/nope", headers=h).status_code == 404
    assert (
        client.get("/admin/prompts/api/prompts/nope", headers={**h, "accept": "application/json"}).json()["error"]
        == "PromptNotFound"
    )


def test_router_options():
    engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    reg = PromptRegistry(engine)
    reg.create_tables()

    async def principal() -> Principal:
        return Principal(id="u", permissions=frozenset({"prompts:admin"}))

    app = FastAPI()
    app.include_router(admin_router(reg, principal=principal, ui=False, include_in_schema=False), prefix="/x")
    with TestClient(app) as c:
        assert c.get("/x/api/health").status_code == 200
        assert c.get("/x/").status_code == 404
        assert c.get("/openapi.json").json()["paths"] == {}


def test_import_export_pages_and_api(client: TestClient):
    client.get("/admin/prompts/", headers={"x-role": "admin"})
    r = client.get("/admin/prompts/export.json", headers={"x-role": "admin"})
    assert r.status_code == 200 and r.headers["content-disposition"].startswith("attachment")
    data = r.json()
    assert data["prompts"][0]["name"] == "support/agent"
    assert client.get("/admin/prompts/export.json", headers={"x-role": "editor"}).status_code == 403
    assert client.get("/admin/prompts/import", headers={"x-role": "admin"}).status_code == 200
    data["prompts"][0]["name"] = "copy/agent"
    r = post(client, "/admin/prompts/import", "admin", data=json.dumps(data), labels="1")
    assert r.status_code == 303 and "1+prompts" in r.headers["location"]
    assert client.reg.get("copy/agent").version == 1  # type: ignore[attr-defined]
    assert post(client, "/admin/prompts/import", "admin", data="not json").status_code == 422
    assert post(client, "/admin/prompts/import", "admin", data="[]").status_code == 422
    assert (
        client.get("/admin/prompts/api/export?names=copy/agent", headers={"x-role": "admin"}).json()["prompts"][0][
            "name"
        ]
        == "copy/agent"
    )
    data["prompts"][0]["name"] = "copy/two"
    r = client.post("/admin/prompts/api/import?set_labels=false", json=data, headers={"x-role": "admin"})
    assert r.json() == {"prompts": 1, "versions": 1, "labels": 0}
    assert client.post("/admin/prompts/api/import", json=data, headers={"x-role": "editor"}).status_code == 403


def test_rollback_target_shown_and_inline_forms(client: TestClient):
    client.reg.create_version("support/agent", "v2 {customer_name} {plan}", message="v2", actor="ann")  # type: ignore[attr-defined]
    client.reg.publish("support/agent", 2, "staging", actor="ann")  # type: ignore[attr-defined]
    r = client.get("/admin/prompts/p/support/agent", headers={"x-role": "admin"})
    assert "Rollback staging: v2 → v1" in r.text
    assert "Rollback production" not in r.text  # production was force-seeded: nothing to roll back to
    assert 'name="reason" placeholder="reason (required)"' in r.text  # inline break-glass reason
    assert "prompt(" not in r.text  # no browser dialogs
    assert 'placeholder="+ locale (fr, pt-BR)"' in r.text


def test_dev_principal(monkeypatch: pytest.MonkeyPatch):
    from promptdeck.fastapi import dev_principal

    reg = PromptRegistry.in_memory()
    app = FastAPI()
    app.include_router(admin_router(reg, principal=dev_principal), prefix="/admin/prompts")
    monkeypatch.delenv("PROMPTDECK_DEV_UI", raising=False)
    with TestClient(app) as c:
        assert c.get("/admin/prompts/").status_code == 503
    monkeypatch.setenv("PROMPTDECK_DEV_UI", "1")
    with TestClient(app) as c:
        assert c.get("/admin/prompts/").status_code == 200
        assert c.get("/admin/prompts/audit").status_code == 200
