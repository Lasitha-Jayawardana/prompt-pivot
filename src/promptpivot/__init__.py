"""promptpivot: store, version, edit and publish LLM prompts at runtime inside your FastAPI app."""

from .errors import (
    PromptConflict,
    PromptNotFound,
    PromptPivotError,
    PromptPolicyError,
    PromptRenderError,
    PromptStoreUnavailable,
    PromptValidationError,
)
from .models import (
    AuditRecord,
    ChangeRequestRecord,
    LabelRecord,
    Message,
    Principal,
    Prompt,
    PromptConfig,
    PromptRecord,
    VersionRecord,
)
from .registry import PromptAccessor, PromptRegistry

__version__ = "0.1.3"


def agent_guide() -> str:
    """The packaged usage guide for developers and coding agents (also ``prompt-pivot docs``)."""
    from importlib.resources import files

    return files(__name__).joinpath("agent-guide.md").read_text(encoding="utf-8")


__all__ = [
    "PromptRegistry",
    "PromptAccessor",
    "Prompt",
    "PromptConfig",
    "Message",
    "Principal",
    "PromptRecord",
    "VersionRecord",
    "LabelRecord",
    "ChangeRequestRecord",
    "AuditRecord",
    "PromptPivotError",
    "PromptNotFound",
    "PromptRenderError",
    "PromptValidationError",
    "PromptStoreUnavailable",
    "PromptConflict",
    "PromptPolicyError",
    "__version__",
    "agent_guide",
]
