"""Public data types: handles, config, messages, principals and records."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Generic, Literal, Type, TypeVar, cast  # noqa: UP035

from pydantic import BaseModel, ConfigDict, ValidationError

from .errors import PromptRenderError, PromptValidationError
from .templating import Renderer

PromptType = Literal["text", "chat"]
PromptFormat = Literal["python", "jinja"]

DEFAULT_LABELS = ("production", "staging", "latest")
"""Built-in labels. ``latest`` moves automatically on every save."""


class PromptConfig(BaseModel):
    """Default typed model settings. Extra keys are kept."""

    model_config = ConfigDict(extra="allow", frozen=True)

    model: str | None = None
    temperature: float | None = None
    max_tokens: int | None = None
    tools: list[dict[str, Any]] | None = None
    response_format: dict[str, Any] | None = None


class Message(BaseModel):
    """One chat message of a ``chat`` prompt."""

    model_config = ConfigDict(frozen=True, extra="allow")

    role: str
    content: str


class Principal(BaseModel):
    """Who is acting. The host app builds one from its own auth."""

    model_config = ConfigDict(frozen=True)

    id: str
    name: str = ""
    permissions: frozenset[str] = frozenset()

    def can(self, permission: str) -> bool:
        """True if the principal holds ``permission`` or ``prompts:admin``."""
        return "prompts:admin" in self.permissions or permission in self.permissions


@dataclass(frozen=True, slots=True)
class FragmentRef:
    """A fragment that was spliced into a handle, and exactly which version of it."""

    name: str
    locale: str
    version: int
    label: str
    """The label it was resolved through, or ``v3`` when the reference pinned a version."""
    checksum: str

    def __str__(self) -> str:
        return f"{self.name}@v{self.version}"


V = TypeVar("V", bound=BaseModel)
C = TypeVar("C", bound=BaseModel)
M = TypeVar("M")


@dataclass(frozen=True, slots=True)
class Prompt(Generic[V, C, M]):
    """Immutable, resolved prompt handle returned by ``get()`` / ``aget()``."""

    name: str
    version: int
    label: str
    locale: str
    requested_locale: str
    type: PromptType
    format: PromptFormat
    template: str | list[Message]
    config: C
    metadata: M
    variables: tuple[str, ...]
    is_fallback: bool = False
    checksum: str = ""
    fragments: tuple[FragmentRef, ...] = ()
    """Fragments resolved into this handle, with the version of each (see ``{> name}`` references)."""
    _renderer: Renderer = field(repr=False, compare=False, default=None)  # type: ignore[assignment]
    _variables_model: Type[V] | None = field(repr=False, compare=False, default=None)  # noqa: UP006

    def compile(self, variables: V | None = None, /, **kwargs: Any) -> str | list[Message]:
        """Render the template. Pass a variables model instance or keyword arguments."""
        if variables is not None:
            if kwargs:
                raise TypeError("pass either a variables model or keyword arguments, not both")
            values = variables.model_dump()
        elif self._variables_model is not None:
            try:
                values = self._variables_model.model_validate(kwargs).model_dump()
            except ValidationError as e:
                raise PromptValidationError(str(e)) from e
        else:
            values = kwargs
        try:
            return cast("str | list[Message]", self._renderer(values))
        except KeyError as e:
            raise PromptRenderError(f"missing variable {e.args[0]!r} for prompt {self.name!r}") from e

    def compile_text(self, variables: V | None = None, /, **kwargs: Any) -> str:
        """``compile()`` for a ``text`` prompt, typed as ``str``."""
        if self.type != "text":
            raise PromptRenderError(f"prompt {self.name!r} is a chat prompt; use compile_messages()")
        return cast(str, self.compile(variables, **kwargs))

    def compile_messages(self, variables: V | None = None, /, **kwargs: Any) -> list[Message]:
        """``compile()`` for a ``chat`` prompt, typed as ``list[Message]``."""
        if self.type != "chat":
            raise PromptRenderError(f"prompt {self.name!r} is a text prompt; use compile_text()")
        return cast("list[Message]", self.compile(variables, **kwargs))

    def trace_attributes(self) -> dict[str, str | int | bool]:
        """OpenTelemetry-ready span attributes."""
        attrs: dict[str, str | int | bool] = {
            "prompt.name": self.name,
            "prompt.version": self.version,
            "prompt.label": self.label,
            "prompt.locale": self.locale,
            "prompt.is_fallback": self.is_fallback,
        }
        if self.fragments:
            attrs["prompt.fragments"] = ",".join(str(f) for f in self.fragments)
        return attrs

    @contextmanager
    def traced(self) -> Iterator[None]:
        """Record this prompt on the current OpenTelemetry span and carry it as baggage.

        Inside the block the current span gets :meth:`trace_attributes`, and the same keys are set
        as baggage so an OpenTelemetry ``BaggageSpanProcessor`` (or your own processor) can copy
        them onto every child span, such as the LLM call. A no-op when OpenTelemetry is absent.
        """
        try:
            from opentelemetry import baggage, context, trace
        except ImportError:
            yield
            return
        attrs = self.trace_attributes()
        span = trace.get_current_span()
        if span.is_recording():
            span.set_attributes(attrs)
        ctx = context.get_current()
        for key, value in attrs.items():
            ctx = baggage.set_baggage(key, str(value), ctx)
        token = context.attach(ctx)
        try:
            yield
        finally:
            context.detach(token)


# --- management records (plain, frozen) ---------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PromptRecord:
    id: int
    name: str
    type: PromptType
    description: str | None
    tags: tuple[str, ...]
    metadata: dict[str, Any]
    archived_at: datetime | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class VersionRecord:
    id: int
    prompt_id: int
    locale: str
    version: int
    format: PromptFormat
    template: str | list[dict[str, Any]]
    config: dict[str, Any]
    variables: tuple[str, ...]
    checksum: str
    message: str
    created_by: str
    created_at: datetime
    notes: dict[str, Any] | None = None
    """Optional per-version notes (ticket link, reviewer remarks). Free-form JSON."""
    warning: str | None = None
    """Set when a locale variant's variables differ from the default locale's production version."""


@dataclass(frozen=True, slots=True)
class LabelRecord:
    id: int
    prompt_id: int
    locale: str
    label: str
    version_id: int
    version: int
    updated_by: str
    updated_at: datetime
    lock_version: int


@dataclass(frozen=True, slots=True)
class ChangeRequestRecord:
    id: int
    prompt_id: int
    name: str
    locale: str
    version_id: int
    version: int
    target_label: str
    status: Literal["open", "approved", "rejected", "published"]
    author: str
    reviewer: str | None
    comment: str | None
    created_at: datetime
    decided_at: datetime | None


@dataclass(frozen=True, slots=True)
class AuditRecord:
    id: int
    at: datetime
    actor: str
    action: str
    target_type: str
    target_id: str
    before: dict[str, Any] | None
    after: dict[str, Any] | None
    reason: str | None
