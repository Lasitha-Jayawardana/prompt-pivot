"""``promptdeck`` command line: migrate, export, import, publish, rollback, list."""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any

from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from .errors import PromptDeckError
from .migrations import upgrade
from .registry import PromptRegistry
from .schema import DEFAULT_PREFIX


def _engine(url: str) -> Any:
    engine = create_engine(url)
    if engine.dialect.is_async:  # asyncpg, aiomysql, aiosqlite: use an AsyncEngine instead
        engine.dispose()
        return create_async_engine(url, poolclass=NullPool)
    return engine


def _load(path: str) -> dict[str, Any]:
    with open(path, encoding="utf-8") as f:
        text = f.read()
    if path.endswith((".yaml", ".yml")):
        import yaml  # optional extra

        return dict(yaml.safe_load(text) or {})
    return dict(json.loads(text))


def _dump(data: dict[str, Any], path: str | None) -> None:
    if path and path.endswith((".yaml", ".yml")):
        import yaml

        text = yaml.safe_dump(data, sort_keys=False, allow_unicode=True, width=120)
    else:
        text = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
    if path:
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
    else:
        sys.stdout.write(text)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="promptdeck", description="Manage promptdeck prompts in a database.")
    ap.add_argument(
        "--url",
        default=os.environ.get("PROMPTDECK_DATABASE_URL"),
        help="SQLAlchemy URL (or env PROMPTDECK_DATABASE_URL)",
    )
    ap.add_argument("--prefix", default=os.environ.get("PROMPTDECK_TABLE_PREFIX", DEFAULT_PREFIX))
    ap.add_argument("--actor", default=os.environ.get("USER", "cli"), help="actor recorded in audit")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("migrate", help="create or upgrade the schema")
    e = sub.add_parser("export", help="export prompts, versions and labels as JSON or YAML")
    e.add_argument("-o", "--output", help="file (.json, .yaml); stdout when omitted")
    e.add_argument("names", nargs="*", help="prompt names (all when omitted)")
    i = sub.add_parser("import", help="import from a JSON or YAML export")
    i.add_argument("file")
    i.add_argument("--no-labels", action="store_true", help="import versions only, do not move labels")
    p = sub.add_parser("publish", help="move a label to a version (force bypasses approval)")
    p.add_argument("name")
    p.add_argument("version", type=int)
    p.add_argument("label")
    p.add_argument("--locale")
    p.add_argument("--reason")
    p.add_argument("--force", action="store_true")
    rb = sub.add_parser("rollback", help="move a label back to its previous version")
    rb.add_argument("name")
    rb.add_argument("label")
    rb.add_argument("--locale")
    rb.add_argument("--reason")
    ls = sub.add_parser("list", help="list prompts and their labels")
    ls.add_argument("-q")
    args = ap.parse_args(argv)
    if not args.url:
        ap.error("--url or PROMPTDECK_DATABASE_URL is required")

    engine = _engine(args.url)
    try:
        if args.cmd == "migrate":
            print(f"schema up to date ({upgrade(engine, args.prefix)})")
            return 0
        reg = PromptRegistry(engine, table_prefix=args.prefix, cache_ttl=0)
        if args.cmd == "export":
            _dump(reg.export(args.names or None), args.output)
        elif args.cmd == "import":
            counts = reg.import_prompts(_load(args.file), actor=args.actor, set_labels=not args.no_labels)
            print(", ".join(f"{v} {k}" for k, v in counts.items()))
        elif args.cmd == "publish":
            lb = reg.publish(
                args.name,
                args.version,
                args.label,
                actor=args.actor,
                locale=args.locale,
                reason=args.reason,
                force=args.force,
            )
            print(f"{args.name} {lb.label} ({lb.locale}) -> v{lb.version}")
        elif args.cmd == "rollback":
            lb = reg.rollback(args.name, args.label, actor=args.actor, locale=args.locale, reason=args.reason)
            print(f"{args.name} {lb.label} ({lb.locale}) -> v{lb.version}")
        elif args.cmd == "list":
            prompts = reg.list_prompts(q=args.q)
            labels = reg._run(reg.store.labels_many, [x.name for x in prompts])
            for pr in prompts:
                tags = ", ".join(f"{x.label}@{x.locale}=v{x.version}" for x in labels[pr.name] if x.label != "latest")
                print(f"{pr.name}\t{pr.type}\t{tags}")
    except PromptDeckError as e:
        print(f"error: {type(e).__name__}: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
