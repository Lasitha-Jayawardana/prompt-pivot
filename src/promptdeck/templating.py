"""Template rendering: a safe ``python`` formatter and a sandboxed ``jinja`` environment.

Both formats are compiled once per version and rendered without I/O.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Sequence
from string import Formatter
from typing import Any

from jinja2 import StrictUndefined, TemplateSyntaxError, meta
from jinja2.exceptions import UndefinedError
from jinja2.sandbox import SandboxedEnvironment

from .errors import PromptRenderError

Renderer = Callable[[dict[str, Any]], Any]
"""Takes variable values and returns a rendered ``str`` or ``list[Message]``."""

TemplateInput = "str | Sequence[dict[str, Any] | Any]"


def normalize_template(template: Any) -> str | list[dict[str, Any]]:
    """Accept a string, a list of dicts, or a list of ``Message``/pydantic objects; return plain data."""
    if isinstance(template, str):
        return template
    out: list[dict[str, Any]] = []
    for m in template:
        if hasattr(m, "model_dump"):
            m = m.model_dump()
        if not isinstance(m, dict) or "role" not in m or "content" not in m:
            raise PromptRenderError("each chat message needs a role and a content")
        out.append(dict(m))
    return out


_formatter = Formatter()
_jinja = SandboxedEnvironment(undefined=StrictUndefined, autoescape=False, keep_trailing_newline=True)


# --- python format ------------------------------------------------------------------------------


def _parse_python(template: str) -> list[tuple[str, str | None, str]]:
    """Parse ``{name}`` fields. Only bare identifiers are allowed; ``{{``/``}}`` escape braces."""
    try:
        parsed = list(_formatter.parse(template))
    except ValueError as e:
        raise PromptRenderError(f"invalid template: {e}") from e
    segments: list[tuple[str, str | None, str]] = []
    for literal, name, spec, conversion in parsed:
        if name is None:
            segments.append((literal, None, ""))
            continue
        if conversion is not None or not name.isidentifier():
            raise PromptRenderError(f"unsafe field {{{name}}}: only plain variable names are allowed")
        if spec and "{" in spec:
            raise PromptRenderError(f"nested fields are not allowed in {{{name}:{spec}}}")
        segments.append((literal, name, spec or ""))
    return segments


def _render_python(segments: Sequence[tuple[str, str | None, str]], values: dict[str, Any]) -> str:
    out: list[str] = []
    for literal, name, spec in segments:
        out.append(literal)
        if name is not None:
            out.append(format(values[name], spec))  # KeyError -> PromptRenderError in handle
    return "".join(out)


# --- jinja format -------------------------------------------------------------------------------


def _compile_jinja(template: str) -> Callable[[dict[str, Any]], str]:
    try:
        compiled = _jinja.from_string(template)
    except TemplateSyntaxError as e:
        raise PromptRenderError(f"invalid jinja template: {e}") from e

    def render(values: dict[str, Any]) -> str:
        try:
            return compiled.render(values)
        except UndefinedError as e:
            raise KeyError(str(e).split("'")[1] if "'" in str(e) else str(e)) from e

    return render


# --- public helpers -----------------------------------------------------------------------------


def detect_variables(template: Any, fmt: str) -> tuple[str, ...]:
    """Return the variable names a template uses, in first-seen order."""
    template = normalize_template(template)
    sources = [template] if isinstance(template, str) else [m.get("content", "") for m in template]
    seen: dict[str, None] = {}
    for src in sources:
        if fmt == "python":
            for _, name, _ in _parse_python(src):
                if name is not None:
                    seen.setdefault(name, None)
        else:
            try:
                ast = _jinja.parse(src)
            except TemplateSyntaxError as e:
                raise PromptRenderError(f"invalid jinja template: {e}") from e
            for name in sorted(meta.find_undeclared_variables(ast)):
                seen.setdefault(name, None)
    return tuple(seen)


def build_renderer(template: Any, fmt: str) -> Renderer:
    """Compile ``template`` into a renderer. Chat templates render each message's content."""
    template = normalize_template(template)
    if fmt not in ("python", "jinja"):
        raise PromptRenderError(f"unknown format {fmt!r}")

    def one(src: str) -> Callable[[dict[str, Any]], str]:
        if fmt == "python":
            segments = _parse_python(src)
            return lambda values: _render_python(segments, values)
        return _compile_jinja(src)

    if isinstance(template, str):
        return one(template)

    from .models import Message  # local import: models imports this module

    parts = [(dict(m), one(str(m.get("content", "")))) for m in template]

    def render_chat(values: dict[str, Any]) -> list[Message]:
        return [Message(**{**m, "content": r(values)}) for m, r in parts]

    return render_chat


def checksum(template: Any, fmt: str, config: dict[str, Any]) -> str:
    """Stable content hash of a version (template + format + config)."""
    template = normalize_template(template)
    payload = json.dumps([template, fmt, config], sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()[:32]
