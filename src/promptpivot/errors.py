"""Typed errors raised by promptpivot. All inherit from :class:`PromptPivotError`."""

from __future__ import annotations


class PromptPivotError(Exception):
    """Base class for every promptpivot error."""


class PromptNotFound(PromptPivotError, LookupError):
    """No prompt, version or label matches the request."""


class PromptRenderError(PromptPivotError, ValueError):
    """A template could not be rendered (missing variable, bad syntax, unsafe field)."""


class PromptValidationError(PromptPivotError, ValueError):
    """Variables, config or metadata failed validation against their model."""


class PromptStoreUnavailable(PromptPivotError, RuntimeError):
    """The database could not be reached and nothing cached or default could be served."""


class PromptConflict(PromptPivotError, RuntimeError):
    """An optimistic lock failed: another writer moved the label first."""


class PromptPolicyError(PromptPivotError, PermissionError):
    """A rule blocked the action: missing approval, same author/approver, permission."""
