"""FastAPI integration: ``admin_router`` serves a JSON API and a small server-rendered UI.

Nothing is exposed unless the host mounts the router. Authentication is the host's: pass a
dependency that returns a :class:`~promptregistry.Principal`.
"""

from __future__ import annotations

import json
import os
import secrets
from collections.abc import Awaitable, Callable, Coroutine, Sequence
from dataclasses import asdict, is_dataclass
from datetime import datetime
from typing import Any
from urllib.parse import parse_qsl, urlencode

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.routing import APIRoute
from jinja2 import Environment, PackageLoader, select_autoescape
from pydantic import BaseModel, Field

from .errors import (
    PromptConflict,
    PromptNotFound,
    PromptPolicyError,
    PromptRegistryError,
    PromptRenderError,
    PromptStoreUnavailable,
    PromptValidationError,
)
from .models import Principal
from .registry import PromptRegistry
from .templating import build_renderer

PrincipalDep = Callable[..., "Principal | Awaitable[Principal]"]
CSRF_COOKIE = "promptregistry_csrf"
DEV_ENV = "PROMPTREGISTRY_DEV_UI"


def dev_principal() -> Principal:
    """Local-development principal with every permission.

    Refuses to run unless the environment variable ``PROMPTREGISTRY_DEV_UI=1`` is set, so it cannot be
    deployed by accident. Never use it behind a public address.
    """
    if os.environ.get(DEV_ENV) != "1":
        raise HTTPException(503, f"promptregistry dev_principal is disabled; set {DEV_ENV}=1 for local development")
    return Principal(id="dev", name="Developer (dev mode)", permissions=frozenset({"prompts:admin"}))


_STATUS = {
    PromptNotFound: 404,
    PromptValidationError: 422,
    PromptRenderError: 422,
    PromptConflict: 409,
    PromptPolicyError: 403,
    PromptStoreUnavailable: 503,
}

_env = Environment(
    loader=PackageLoader("promptregistry", "templates"),
    autoescape=select_autoescape(["html"]),
    trim_blocks=True,
    lstrip_blocks=True,
)
_env.filters["json"] = lambda v, indent=2: json.dumps(v, indent=indent, sort_keys=True, default=str)


def _plain(obj: Any) -> Any:
    """Dataclass/records -> JSON-safe data."""
    if is_dataclass(obj) and not isinstance(obj, type):
        return {k: _plain(v) for k, v in asdict(obj).items()}
    if isinstance(obj, dict):
        return {k: _plain(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_plain(v) for v in obj]
    if isinstance(obj, datetime):
        return obj.isoformat()
    return obj


class _Route(APIRoute):
    """Maps promptregistry errors to HTTP status codes for both the API and the UI."""

    def get_route_handler(self) -> Callable[[Request], Coroutine[Any, Any, Response]]:
        handler = super().get_route_handler()

        async def wrapped(request: Request) -> Response:
            try:
                return await handler(request)
            except PromptRegistryError as e:
                status = next((s for t, s in _STATUS.items() if isinstance(e, t)), 400)
                if "/api/" in request.url.path or request.headers.get("accept", "").startswith("application/json"):
                    return JSONResponse({"error": type(e).__name__, "detail": str(e)}, status)
                return HTMLResponse(
                    _env.get_template("error.html").render(
                        status=status, error=type(e).__name__, detail=str(e), request=request
                    ),
                    status,
                )

        return wrapped


# --- request bodies (API) -------------------------------------------------------------------------


class CreatePromptBody(BaseModel):
    name: str
    type: str = "text"
    description: str | None = None
    tags: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class VersionBody(BaseModel):
    template: str | list[dict[str, Any]]
    format: str = "python"
    locale: str | None = None
    config: dict[str, Any] = Field(default_factory=dict)
    message: str = ""


class MetadataBody(BaseModel):
    metadata: dict[str, Any]


class PublishBody(BaseModel):
    version: int
    label: str
    locale: str | None = None
    expected_current: int | None = None
    reason: str | None = None
    force: bool = False


class LabelBody(BaseModel):
    label: str
    locale: str | None = None
    reason: str | None = None


class ChangeRequestBody(BaseModel):
    version: int
    label: str
    locale: str | None = None
    comment: str | None = None


class DecisionBody(BaseModel):
    comment: str | None = None


class PreviewBody(BaseModel):
    version: int
    locale: str | None = None
    variables: dict[str, Any] = Field(default_factory=dict)


# --- router -------------------------------------------------------------------------------------


def admin_router(
    registry: PromptRegistry,
    *,
    principal: PrincipalDep,
    include_in_schema: bool = True,
    ui: bool = True,
    tags: Sequence[str] | None = None,
) -> APIRouter:
    """Build the admin router. Mount it with ``app.include_router(r, prefix="/admin/prompts")``.

    ``principal`` is a FastAPI dependency (sync or async) returning the acting
    :class:`Principal`; permission checks use its ``permissions`` set.
    """
    r = APIRouter(route_class=_Route, include_in_schema=include_in_schema, tags=list(tags or ["promptregistry"]))

    def need(permission: str) -> Callable[..., Awaitable[Principal]]:
        async def dep(p: Principal = Depends(principal)) -> Principal:
            if not p.can(permission):
                raise HTTPException(403, f"missing permission {permission!r}")
            return p

        return dep

    async def json_only(request: Request) -> None:
        if not request.headers.get("content-type", "").startswith("application/json"):
            raise HTTPException(415, "send application/json")

    # ---- API -----------------------------------------------------------------------------------

    @r.get("/api/health")
    async def health(_: Principal = Depends(need("prompts:read"))) -> Any:
        return await registry.ahealth()

    @r.get("/api/prompts")
    async def api_list(
        q: str | None = None,
        tag: str | None = None,
        include_archived: bool = False,
        _: Principal = Depends(need("prompts:read")),
    ) -> Any:
        return _plain(await registry.alist_prompts(q=q, tag=tag, include_archived=include_archived))

    @r.post("/api/prompts", status_code=201, dependencies=[Depends(json_only)])
    async def api_create(body: CreatePromptBody, p: Principal = Depends(need("prompts:edit"))) -> Any:
        rec = await registry.acreate_prompt(
            body.name, body.type, actor=p.id, description=body.description, tags=body.tags, metadata=body.metadata
        )
        return _plain(rec)

    @r.get("/api/change-requests")
    async def api_crs(
        name: str | None = None, status: str | None = None, _: Principal = Depends(need("prompts:read"))
    ) -> Any:
        return _plain(await registry.alist_change_requests(name, status))

    @r.post("/api/change-requests/{cr_id}/approve", dependencies=[Depends(json_only)])
    async def api_approve(cr_id: int, body: DecisionBody, p: Principal = Depends(need("prompts:approve"))) -> Any:
        return _plain(await registry.aapprove(cr_id, actor=p.id, comment=body.comment))

    @r.post("/api/change-requests/{cr_id}/reject", dependencies=[Depends(json_only)])
    async def api_reject(cr_id: int, body: DecisionBody, p: Principal = Depends(need("prompts:approve"))) -> Any:
        return _plain(await registry.areject(cr_id, actor=p.id, comment=body.comment))

    @r.get("/api/export")
    async def api_export(names: str | None = None, _: Principal = Depends(need("prompts:admin"))) -> Any:
        return await registry.aexport(names.split(",") if names else None)

    @r.post("/api/import", dependencies=[Depends(json_only)])
    async def api_import(
        body: dict[str, Any], set_labels: bool = True, p: Principal = Depends(need("prompts:admin"))
    ) -> Any:
        return await registry.aimport_prompts(body, actor=p.id, set_labels=set_labels)

    @r.get("/api/audit")
    async def api_audit(
        target_type: str | None = None,
        target_id: str | None = None,
        actor: str | None = None,
        limit: int = 200,
        _: Principal = Depends(need("prompts:admin")),
    ) -> Any:
        return _plain(await registry.aaudit(target_type=target_type, target_id=target_id, actor=actor, limit=limit))

    @r.get("/api/prompts/{name:path}/diff")
    async def api_diff(
        name: str, a: int, b: int, locale: str | None = None, _: Principal = Depends(need("prompts:read"))
    ) -> Any:
        return {"name": name, "a": a, "b": b, "diff": await registry.adiff(name, a, b, locale)}

    @r.post("/api/prompts/{name:path}/versions", status_code=201, dependencies=[Depends(json_only)])
    async def api_version(name: str, body: VersionBody, p: Principal = Depends(need("prompts:edit"))) -> Any:
        rec = await registry.acreate_version(
            name,
            body.template,
            format=body.format,
            message=body.message,
            actor=p.id,
            locale=body.locale,
            config=body.config,
        )
        return _plain(rec)

    @r.put("/api/prompts/{name:path}/metadata", dependencies=[Depends(json_only)])
    async def api_metadata(name: str, body: MetadataBody, p: Principal = Depends(need("prompts:edit"))) -> Any:
        return _plain(await registry.aupdate_metadata(name, body.metadata, actor=p.id))

    @r.post("/api/prompts/{name:path}/publish", dependencies=[Depends(json_only)])
    async def api_publish(name: str, body: PublishBody, p: Principal = Depends(principal)) -> Any:
        _can_publish(p, body.label, body.force)
        rec = await registry.apublish(
            name,
            body.version,
            body.label,
            actor=p.id,
            locale=body.locale,
            expected_current=body.expected_current,
            reason=body.reason,
            force=body.force,
        )
        return _plain(rec)

    @r.post("/api/prompts/{name:path}/rollback", dependencies=[Depends(json_only)])
    async def api_rollback(name: str, body: LabelBody, p: Principal = Depends(principal)) -> Any:
        _can_publish(p, body.label, False)
        return _plain(await registry.arollback(name, body.label, actor=p.id, locale=body.locale, reason=body.reason))

    @r.post("/api/prompts/{name:path}/change-requests", status_code=201, dependencies=[Depends(json_only)])
    async def api_request(name: str, body: ChangeRequestBody, p: Principal = Depends(need("prompts:edit"))) -> Any:
        return _plain(
            await registry.arequest_change(
                name,
                body.version,
                body.label,
                actor=p.id,
                locale=body.locale,
                comment=body.comment,
            )
        )

    @r.post("/api/prompts/{name:path}/preview", dependencies=[Depends(json_only)])
    async def api_preview(name: str, body: PreviewBody, _: Principal = Depends(need("prompts:read"))) -> Any:
        return {"rendered": _plain(await _preview(registry, name, body.version, body.locale, body.variables))}

    @r.post("/api/prompts/{name:path}/archive", dependencies=[Depends(json_only)])
    async def api_archive(name: str, p: Principal = Depends(need("prompts:admin"))) -> Any:
        return _plain(await registry.aarchive(name, actor=p.id))

    @r.get("/api/prompts/{name:path}")
    async def api_get(name: str, _: Principal = Depends(need("prompts:read"))) -> Any:
        return {
            "prompt": _plain(await registry.aget_prompt(name)),
            "labels": _plain(await registry.alabels(name)),
            "versions": _plain(await registry.ahistory(name)),
        }

    if ui:
        _add_ui(r, registry, principal, need)
    return r


def _can_publish(p: Principal, label: str, force: bool) -> None:
    if force and not p.can("prompts:admin"):
        raise HTTPException(403, "break-glass publish needs prompts:admin")
    if not p.can(f"prompts:publish:{label}"):
        raise HTTPException(403, f"missing permission 'prompts:publish:{label}'")


async def _preview(
    registry: PromptRegistry, name: str, version: int, locale: str | None, variables: dict[str, Any]
) -> Any:
    locale = locale or registry.default_locale
    for v in await registry.ahistory(name, locale):
        if v.version == version:
            try:
                return build_renderer(v.template, v.format)(variables)
            except KeyError as e:
                raise PromptRenderError(f"missing variable {e.args[0]!r}") from e
    raise PromptNotFound(f"version {version} ({locale}) does not exist")


# --- server-rendered UI -------------------------------------------------------------------------


def _add_ui(
    r: APIRouter,
    registry: PromptRegistry,
    principal: PrincipalDep,
    need: Callable[[str], Callable[..., Awaitable[Principal]]],
) -> None:

    def csrf_token(request: Request) -> tuple[str, bool]:
        tok = request.cookies.get(CSRF_COOKIE)
        return (tok, False) if tok and len(tok) >= 32 else (secrets.token_urlsafe(32), True)

    def page(request: Request, template: str, p: Principal, **ctx: Any) -> HTMLResponse:
        tok, new = csrf_token(request)
        html = _env.get_template(template).render(
            request=request,
            principal=p,
            csrf=tok,
            environment=registry.environment,
            protected=registry.protected_labels,
            default_locale=registry.default_locale,
            ok=request.query_params.get("ok"),
            err=request.query_params.get("err"),
            **ctx,
        )
        resp = HTMLResponse(html)
        if new:
            resp.set_cookie(CSRF_COOKIE, tok, httponly=True, samesite="strict", secure=request.url.scheme == "https")
        return resp

    async def form(request: Request) -> dict[str, str]:
        # Plain urlencoded forms parsed with the stdlib: no python-multipart dependency.
        if not request.headers.get("content-type", "").startswith("application/x-www-form-urlencoded"):
            raise HTTPException(415, "expected an application/x-www-form-urlencoded form")
        data = dict(parse_qsl((await request.body()).decode("utf-8", "replace"), keep_blank_values=True))
        tok = request.cookies.get(CSRF_COOKIE)
        if not tok or not secrets.compare_digest(tok, data.get("csrf", "")):
            raise HTTPException(403, "CSRF token missing or invalid; reload the page")
        return data

    def back(request: Request, name: str | None, locale: str | None = None, **flash: str | None) -> RedirectResponse:
        url = request.url_for("promptregistry_prompt", name=name) if name else request.url_for("promptregistry_index")
        q = {k: v for k, v in {"locale": locale, **flash}.items() if v}
        return RedirectResponse(f"{url}?{urlencode(q)}" if q else str(url), status_code=303)

    def loads(text: str, what: str) -> dict[str, Any]:
        text = text.strip()
        if not text:
            return {}
        try:
            data = json.loads(text)
        except ValueError as e:
            raise PromptValidationError(f"{what}: invalid JSON ({e})") from e
        if not isinstance(data, dict):
            raise PromptValidationError(f"{what}: must be a JSON object")
        return data

    @r.get("/", response_class=HTMLResponse, name="promptregistry_index")
    async def index(
        request: Request, q: str | None = None, tag: str | None = None, p: Principal = Depends(need("prompts:read"))
    ) -> HTMLResponse:
        prompts = await registry.alist_prompts(q=q, tag=tag)
        labels = await registry._arun(registry.store.labels_many, [x.name for x in prompts])
        open_crs = await registry.alist_change_requests(status="open")
        return page(
            request, "index.html", p, prompts=prompts, labels=labels, q=q or "", tag=tag or "", open_crs=open_crs
        )

    @r.get("/new", response_class=HTMLResponse, name="promptregistry_new")
    async def new_form(request: Request, p: Principal = Depends(need("prompts:edit"))) -> HTMLResponse:
        return page(request, "new.html", p)

    @r.post("/new", name="promptregistry_create")
    async def create(
        request: Request, p: Principal = Depends(need("prompts:edit")), f: dict[str, str] = Depends(form)
    ) -> RedirectResponse:
        tags = [t.strip() for t in f.get("tags", "").split(",") if t.strip()]
        await registry.acreate_prompt(
            f["name"].strip(),
            f.get("type", "text"),
            actor=p.id,
            description=f.get("description") or None,
            tags=tags,
            metadata=loads(f.get("metadata", ""), "metadata"),
        )
        return back(request, f["name"].strip(), ok="Prompt created. Save a first version below.")

    @r.get("/audit", response_class=HTMLResponse, name="promptregistry_audit")
    async def audit(
        request: Request,
        target: str | None = None,
        actor: str | None = None,
        p: Principal = Depends(need("prompts:admin")),
    ) -> HTMLResponse:
        rows = await registry.aaudit(target_id=target or None, actor=actor or None)
        return page(request, "audit.html", p, rows=rows, target=target or "", actor=actor or "")

    @r.get("/export.json", name="promptregistry_export")
    async def export_json(_: Principal = Depends(need("prompts:admin"))) -> JSONResponse:
        data = await registry.aexport()
        return JSONResponse(data, headers={"content-disposition": 'attachment; filename="promptregistry-export.json"'})

    @r.get("/import", response_class=HTMLResponse, name="promptregistry_import")
    async def import_form(request: Request, p: Principal = Depends(need("prompts:admin"))) -> HTMLResponse:
        return page(request, "import.html", p)

    @r.post("/import", name="promptregistry_import_post")
    async def import_post(
        request: Request, p: Principal = Depends(need("prompts:admin")), f: dict[str, str] = Depends(form)
    ) -> RedirectResponse:
        try:
            data = json.loads(f.get("data") or "")
        except ValueError as e:
            raise PromptValidationError(f"invalid JSON: {e}") from e
        if not isinstance(data, dict) or "prompts" not in data:
            raise PromptValidationError('expected an export object with a "prompts" list')
        counts = await registry.aimport_prompts(data, actor=p.id, set_labels=f.get("labels") == "1")
        return back(request, None, ok=", ".join(f"{v} {k}" for k, v in counts.items()) + " imported.")

    @r.post("/cr/{cr_id}/approve", name="promptregistry_approve")
    async def approve(
        request: Request, cr_id: int, p: Principal = Depends(need("prompts:approve")), f: dict[str, str] = Depends(form)
    ) -> RedirectResponse:
        cr = await registry.aapprove(cr_id, actor=p.id, comment=f.get("comment") or None)
        return back(request, cr.name, cr.locale, ok=f"Change request #{cr.id} approved.")

    @r.post("/cr/{cr_id}/reject", name="promptregistry_reject")
    async def reject(
        request: Request, cr_id: int, p: Principal = Depends(need("prompts:approve")), f: dict[str, str] = Depends(form)
    ) -> RedirectResponse:
        cr = await registry.areject(cr_id, actor=p.id, comment=f.get("comment") or None)
        return back(request, cr.name, cr.locale, ok=f"Change request #{cr.id} rejected.")

    @r.get("/p/{name:path}/diff", response_class=HTMLResponse, name="promptregistry_diff")
    async def diff(
        request: Request,
        name: str,
        a: int,
        b: int,
        locale: str | None = None,
        p: Principal = Depends(need("prompts:read")),
    ) -> HTMLResponse:
        text = await registry.adiff(name, a, b, locale)
        return page(
            request,
            "diff.html",
            p,
            name=name,
            a=a,
            b=b,
            locale=locale or registry.default_locale,
            diff=text or "(no differences)",
        )

    @r.post("/p/{name:path}/versions", name="promptregistry_version")
    async def save_version(
        request: Request, name: str, p: Principal = Depends(need("prompts:edit")), f: dict[str, str] = Depends(form)
    ) -> RedirectResponse:
        prompt = await registry.aget_prompt(name)
        template: str | list[dict[str, Any]]
        if prompt.type == "chat":
            raw = json.loads(f.get("template") or "[]")
            if not isinstance(raw, list) or not all(
                isinstance(m, dict) and "role" in m and "content" in m for m in raw
            ):
                raise PromptValidationError("chat template must be a JSON list of {role, content} messages")
            template = raw
        else:
            template = f.get("template", "")
        rec = await registry.acreate_version(
            name,
            template,
            format=f.get("format", "python"),
            message=f.get("message") or "",
            actor=p.id,
            locale=f.get("locale") or None,
            config=loads(f.get("config", ""), "config"),
        )
        msg = f"Saved v{rec.version} ({rec.locale})." + (f" Warning: {rec.warning}" if rec.warning else "")
        return back(request, name, rec.locale, ok=msg)

    @r.post("/p/{name:path}/metadata", name="promptregistry_metadata")
    async def save_metadata(
        request: Request, name: str, p: Principal = Depends(need("prompts:edit")), f: dict[str, str] = Depends(form)
    ) -> RedirectResponse:
        tags = [t.strip() for t in f.get("tags", "").split(",") if t.strip()]
        await registry.aupdate_prompt(name, actor=p.id, description=f.get("description", ""), tags=tags)
        await registry.aupdate_metadata(name, loads(f.get("metadata", ""), "metadata"), actor=p.id)
        return back(request, name, f.get("locale"), ok="Metadata saved.")

    @r.post("/p/{name:path}/publish", name="promptregistry_publish")
    async def publish(
        request: Request, name: str, p: Principal = Depends(principal), f: dict[str, str] = Depends(form)
    ) -> RedirectResponse:
        label, locale, force = f["label"], f.get("locale") or None, f.get("force") == "1"
        _can_publish(p, label, force)
        expected = int(f["expected_current"]) if f.get("expected_current") else None
        rec = await registry.apublish(
            name,
            int(f["version"]),
            label,
            actor=p.id,
            locale=locale,
            expected_current=expected,
            reason=f.get("reason") or None,
            force=force,
        )
        return back(request, name, locale, ok=f"{label} ({rec.locale}) now points to v{rec.version}.")

    @r.post("/p/{name:path}/request", name="promptregistry_request")
    async def request_change(
        request: Request, name: str, p: Principal = Depends(need("prompts:edit")), f: dict[str, str] = Depends(form)
    ) -> RedirectResponse:
        cr = await registry.arequest_change(
            name,
            int(f["version"]),
            f["label"],
            actor=p.id,
            locale=f.get("locale") or None,
            comment=f.get("comment") or None,
        )
        return back(request, name, cr.locale, ok=f"Change request #{cr.id} opened for {cr.target_label}.")

    @r.post("/p/{name:path}/rollback", name="promptregistry_rollback")
    async def rollback(
        request: Request, name: str, p: Principal = Depends(principal), f: dict[str, str] = Depends(form)
    ) -> RedirectResponse:
        _can_publish(p, f["label"], False)
        rec = await registry.arollback(name, f["label"], actor=p.id, locale=f.get("locale") or None)
        return back(request, name, rec.locale, ok=f"Rolled {f['label']} ({rec.locale}) back to v{rec.version}.")

    @r.post("/p/{name:path}/preview", response_class=HTMLResponse, name="promptregistry_preview")
    async def preview(
        request: Request, name: str, p: Principal = Depends(need("prompts:read")), f: dict[str, str] = Depends(form)
    ) -> HTMLResponse:
        locale = f.get("locale") or registry.default_locale
        rendered = await _preview(registry, name, int(f["version"]), locale, loads(f.get("variables", ""), "variables"))
        return page(
            request,
            "preview.html",
            p,
            name=name,
            version=int(f["version"]),
            locale=locale,
            rendered=rendered if isinstance(rendered, str) else _plain(rendered),
        )

    @r.post("/p/{name:path}/archive", name="promptregistry_archive")
    async def archive(
        request: Request, name: str, p: Principal = Depends(need("prompts:admin")), f: dict[str, str] = Depends(form)
    ) -> RedirectResponse:
        await registry.aarchive(name, actor=p.id, archived=f.get("undo") != "1")
        return back(request, None, ok=f"{name} archived." if f.get("undo") != "1" else f"{name} restored.")

    @r.get("/p/{name:path}", response_class=HTMLResponse, name="promptregistry_prompt")
    async def prompt_page(
        request: Request, name: str, locale: str | None = None, p: Principal = Depends(need("prompts:read"))
    ) -> HTMLResponse:
        prompt = await registry.aget_prompt(name)
        versions = await registry.ahistory(name)
        labels = await registry.alabels(name)
        crs = [c for c in await registry.alist_change_requests(name) if c.status in ("open", "approved")]
        locales = sorted({v.locale for v in versions} | {registry.default_locale})
        locale = locale if locale in locales or locale else registry.default_locale
        here = [v for v in versions if v.locale == locale]
        latest = here[0] if here else None
        label_map: dict[int, list[str]] = {}
        current: dict[str, int] = {}
        rollback_to: dict[str, int] = {}
        for lb in labels:
            if lb.locale == locale:
                label_map.setdefault(lb.version_id, []).append(lb.label)
                current[lb.label] = lb.version
                if lb.label != "latest":
                    target = await registry._arun(registry.store.rollback_target, name, lb.label, locale)
                    if target is not None:
                        rollback_to[lb.label] = target
        template_text = (
            (latest.template if isinstance(latest.template, str) else json.dumps(latest.template, indent=2))
            if latest
            else (
                ""
                if prompt.type == "text"
                else '[\n  {"role": "system", "content": ""},\n  {"role": "user", "content": "{question}"}\n]'
            )
        )
        return page(
            request,
            "prompt.html",
            p,
            prompt=prompt,
            versions=here,
            labels=labels,
            label_map=label_map,
            crs=crs,
            locales=locales,
            locale=locale,
            latest=latest,
            template_text=template_text,
            tags=", ".join(prompt.tags),
            current=current,
            rollback_to=rollback_to,
        )
