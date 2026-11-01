"""Generate docs/reference.md from the installed package. Run: python docs/gen_reference.py

The test suite checks the committed file matches, so the reference can never drift from the code.
"""

from __future__ import annotations

import inspect
import sys
from pathlib import Path
from typing import Any

import promptpivot
from promptpivot import errors, fastapi, migrations, models, registry, templating

OUT = Path(__file__).with_name("reference.md")


def sig(obj: Any) -> str:
    try:
        return str(inspect.signature(obj)).replace("promptpivot.", "")
    except (TypeError, ValueError):
        return "(...)"


def doc(obj: Any) -> str:
    return inspect.cleandoc(obj.__doc__ or "").strip()


def section_class(cls: type, *, methods: bool = True, fields: bool = False) -> list[str]:
    out = [f"### `{cls.__name__}`", "", doc(cls), ""]
    if fields and hasattr(cls, "__dataclass_fields__"):
        out += ["| Field | Type |", "| --- | --- |"]
        for name, f in cls.__dataclass_fields__.items():
            if name.startswith("_"):
                continue
            t = f.type if isinstance(f.type, str) else getattr(f.type, "__name__", str(f.type))
            out.append(f"| `{name}` | `{t}` |")
        out.append("")
    if fields and hasattr(cls, "model_fields"):
        out += ["| Field | Type | Default |", "| --- | --- | --- |"]
        for name, f in cls.model_fields.items():
            ann = getattr(f.annotation, "__name__", str(f.annotation)).replace("typing.", "")
            default = "required" if f.is_required() else repr(f.default)
            out.append(f"| `{name}` | `{ann}` | {default} |")
        out.append("")
    if methods:
        for name, m in inspect.getmembers(cls, lambda x: inspect.isfunction(x) or isinstance(x, classmethod)):
            if name.startswith("_") or name in ("dict", "json", "copy", "construct", "validate"):
                continue
            if (
                name.startswith("model_")
                or name.startswith("schema")
                or name.startswith("parse_")
                or name in ("from_orm", "update_forward_refs")
            ):
                continue
            fn = m.__func__ if isinstance(m, classmethod) else m
            prefix = "async " if inspect.iscoroutinefunction(fn) else ""
            out += [f"#### `{prefix}{cls.__name__}.{name}{sig(fn)}`", "", doc(fn), ""]
    return out


def section_funcs(title: str, items: list[Any]) -> list[str]:
    out = [f"### {title}", ""]
    for fn in items:
        prefix = "async " if inspect.iscoroutinefunction(fn) else ""
        out += [f"#### `{prefix}{fn.__module__.replace('promptpivot.', '')}.{fn.__name__}{sig(fn)}`", "", doc(fn), ""]
    return out


def main() -> str:
    lines = [
        "# prompt-pivot API reference",
        "",
        f"Generated from `promptpivot` {promptpivot.__version__} by `docs/gen_reference.py`. Do not edit by hand.",
        "",
        "Import everything below from `promptpivot` unless a module path is shown.",
        "",
        "## Registry",
        "",
        *section_class(registry.PromptRegistry),
        *section_class(registry.PromptAccessor),
        "## Handles and records",
        "",
        *section_class(models.Prompt, fields=True),
        *section_class(models.FragmentRef, methods=False, fields=True),
        *section_class(models.PromptConfig, methods=False, fields=True),
        *section_class(models.Message, methods=False, fields=True),
        *section_class(models.Principal, fields=True),
        *section_class(models.PromptRecord, methods=False, fields=True),
        *section_class(models.VersionRecord, methods=False, fields=True),
        *section_class(models.LabelRecord, methods=False, fields=True),
        *section_class(models.ChangeRequestRecord, methods=False, fields=True),
        *section_class(models.AuditRecord, methods=False, fields=True),
        "## Errors",
        "",
        "All inherit from `PromptPivotError`.",
        "",
    ]
    for name in errors.__dict__:
        obj = getattr(errors, name)
        if inspect.isclass(obj) and issubclass(obj, errors.PromptPivotError) and obj.__module__ == errors.__name__:
            bases = ", ".join(b.__name__ for b in obj.__bases__)
            lines += [f"- `{name}` ({bases}): {doc(obj)}"]
    lines += [
        "",
        "## FastAPI",
        "",
        *section_funcs("promptpivot.fastapi", [fastapi.admin_router, fastapi.dev_principal]),
    ]
    lines += [
        "## Migrations",
        "",
        *section_funcs("promptpivot.migrations", [migrations.upgrade, migrations.aupgrade, migrations.upgrade_sync]),
    ]
    lines += [
        "## Templating helpers",
        "",
        *section_funcs(
            "promptpivot.templating",
            [templating.detect_variables, templating.fragment_refs, templating.guess_format, templating.build_renderer],
        ),
    ]
    lines += [
        "## CLI",
        "",
        "```",
        "prompt-pivot [--url URL] [--prefix PREFIX] [--actor ACTOR] <command>",
        "  migrate                      create or upgrade the schema",
        "  list [-q TEXT]               prompts and their labels",
        "  export [-o FILE] [NAME ...]  JSON (.json) or YAML (.yaml, needs prompt-pivot[yaml]); stdout without -o",
        "  import FILE [--no-labels]    create missing prompts/versions; set labels unless --no-labels",
        "  publish NAME VERSION LABEL [--locale L] [--reason R] [--force]",
        "  rollback NAME LABEL [--locale L] [--reason R]",
        "  docs                         print the agent guide (how to use the library correctly)",
        "```",
        "",
        "`--url` defaults to `PROMPTPIVOT_DATABASE_URL`; `--prefix` to `PROMPTPIVOT_TABLE_PREFIX`.",
        "",
    ]
    return "\n".join(lines).rstrip() + "\n"


if __name__ == "__main__":
    text = main()
    if "--check" in sys.argv:
        sys.exit(0 if OUT.read_text() == text else 1)
    OUT.write_text(text)
    print(f"wrote {OUT} ({len(text.splitlines())} lines)")
