"""promptpivot: store, version, edit and publish LLM prompts at runtime inside your FastAPI app.

Before writing code against this package, read the usage rules: ``promptpivot.agent_guide()`` or
``prompt-pivot docs`` on the command line. They match the installed version. ``prompt-pivot skill``
writes the same rules as an Agent Skill (``SKILL.md``) into a project so coding agents load them
on their own.
"""

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

__version__ = "0.2.1"


SKILL_NAME = "prompt-pivot"
_SKILL_DESCRIPTION = (
    "Use when writing or changing Python code that reads, defines or manages LLM prompts with the "
    "prompt-pivot library (import promptpivot: PromptRegistry, prompts.get/aget, define, admin_router, "
    "labels, locales, fragments, change requests). Gives the sync/async forms, template brace rules, "
    "publish and approval flow, permissions and error handling for the installed version."
)


def agent_guide() -> str:
    """The packaged usage guide for developers and coding agents (also ``prompt-pivot docs``)."""
    from importlib.resources import files

    return files(__name__).joinpath("agent-guide.md").read_text(encoding="utf-8")


def agent_skill() -> str:
    """The usage guide as an Agent Skill: ``SKILL.md`` text with YAML front matter.

    Write it to ``<project>/.claude/skills/prompt-pivot/SKILL.md`` (or your agent's skills directory)
    with ``prompt-pivot skill``; coding agents then load the rules without being told to.
    """
    return (
        "---\n"
        f"name: {SKILL_NAME}\n"
        f"description: {_SKILL_DESCRIPTION}\n"
        "license: Apache-2.0\n"
        "metadata:\n"
        f'  version: "{__version__}"\n'
        "  source: https://github.com/Lasitha-Jayawardana/prompt-pivot\n"
        "---\n\n" + agent_guide()
    )


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
    "agent_skill",
]
