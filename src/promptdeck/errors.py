"""Typed errors raised by promptdeck. All inherit from :class:`PromptDeckError`."""

from __future__ import annotations


class PromptDeckError(Exception):
    """Base class for every promptdeck error."""


class PromptNotFound(PromptDeckError, LookupError):
    """No prompt, version or label matches the request."""


class PromptRenderError(PromptDeckError, ValueError):
    """A template could not be rendered (missing variable, bad syntax, unsafe field)."""


class PromptValidationError(PromptDeckError, ValueError):
    """Variables, config or metadata failed validation against their model."""


class PromptStoreUnavailable(PromptDeckError, RuntimeError):
    """The database could not be reached and nothing cached or default could be served."""


class PromptConflict(PromptDeckError, RuntimeError):
    """An optimistic lock failed: another writer moved the label first."""


class PromptPolicyError(PromptDeckError, PermissionError):
    """A rule blocked the action: missing approval, same author/approver, permission."""
