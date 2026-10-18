"""Typed errors raised by promptregistry. All inherit from :class:`PromptRegistryError`."""

from __future__ import annotations


class PromptRegistryError(Exception):
    """Base class for every promptregistry error."""


class PromptNotFound(PromptRegistryError, LookupError):
    """No prompt, version or label matches the request."""


class PromptRenderError(PromptRegistryError, ValueError):
    """A template could not be rendered (missing variable, bad syntax, unsafe field)."""


class PromptValidationError(PromptRegistryError, ValueError):
    """Variables, config or metadata failed validation against their model."""


class PromptStoreUnavailable(PromptRegistryError, RuntimeError):
    """The database could not be reached and nothing cached or default could be served."""


class PromptConflict(PromptRegistryError, RuntimeError):
    """An optimistic lock failed: another writer moved the label first."""


class PromptPolicyError(PromptRegistryError, PermissionError):
    """A rule blocked the action: missing approval, same author/approver, permission."""
