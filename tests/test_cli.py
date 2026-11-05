from __future__ import annotations

import json
from pathlib import Path

import pytest

from promptpivot import PromptRegistry
from promptpivot._compat import PYDANTIC_V2
from promptpivot.cli import main
from promptpivot.migrations import upgrade
from tests.conftest import seed


@pytest.fixture(params=["sqlite:///{p}/c.db", "sqlite+aiosqlite:///{p}/c.db"])
def url(request, tmp_path):
    return request.param.format(p=tmp_path)


def test_cli_roundtrip(url: str, tmp_path, capsys, monkeypatch):
    sync_url = url.replace("+aiosqlite", "")
    assert main(["--url", url, "migrate"]) == 0
    assert "alembic" in capsys.readouterr().out
    assert main(["--url", url, "migrate"]) == 0  # idempotent
    capsys.readouterr()
    from sqlalchemy import create_engine

    reg = PromptRegistry(create_engine(sync_url), cache_ttl=0)
    seed(reg)
    out = tmp_path / "x.yaml"
    assert main(["--url", url, "export", "-o", str(out)]) == 0
    assert "support/agent" in out.read_text()
    assert main(["--url", url, "export"]) == 0
    assert json.loads(capsys.readouterr().out)["prompts"][0]["name"] == "support/agent"
    data = json.loads(json.dumps(reg.export()))
    data["prompts"][0]["name"] = "copy/agent"
    (tmp_path / "in.json").write_text(json.dumps(data))
    assert main(["--url", url, "--actor", "me", "import", str(tmp_path / "in.json")]) == 0
    assert "1 prompts, 1 versions, 2 labels" in capsys.readouterr().out
    assert main(["--url", url, "list", "-q", "copy"]) == 0
    assert "copy/agent" in capsys.readouterr().out
    reg.create_version("copy/agent", "v2", message="m", actor="a")
    assert main(["--url", url, "publish", "copy/agent", "2", "staging"]) == 0
    assert main(["--url", url, "publish", "copy/agent", "2", "production"]) == 1  # protected
    assert "PromptPolicyError" in capsys.readouterr().err
    assert main(["--url", url, "publish", "copy/agent", "2", "production", "--force", "--reason", "r"]) == 0
    assert main(["--url", url, "rollback", "copy/agent", "production"]) == 0
    assert "-> v1" in capsys.readouterr().out
    assert reg.get("copy/agent", ttl=0).version == 1
    monkeypatch.delenv("PROMPTPIVOT_DATABASE_URL", raising=False)
    with pytest.raises(SystemExit):
        main(["list"])


def test_migrations_fallback_without_alembic(tmp_path, monkeypatch):
    import builtins

    from sqlalchemy import create_engine, inspect

    real = builtins.__import__

    def fake(name, *a, **k):
        if name.startswith("alembic"):
            raise ImportError(name)
        return real(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", fake)
    engine = create_engine(f"sqlite:///{tmp_path}/m.db")
    assert upgrade(engine, "zz_") == "create_all"
    assert "zz_prompts" in inspect(engine).get_table_names()


def test_migration_from_initial_schema(tmp_path):
    """A database at revision 0001 (no notes column) is upgraded in place; a fresh one is stamped head."""
    from alembic.config import Config
    from alembic.script import ScriptDirectory
    from sqlalchemy import create_engine, inspect, text

    from promptpivot.migrations import HERE
    from promptpivot.schema import build_tables

    url = f"sqlite:///{tmp_path}/old.db"
    engine = create_engine(url)
    build_tables("zz_").metadata.create_all(engine)
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE zz_versions DROP COLUMN notes"))
        conn.execute(text("CREATE TABLE zz_alembic_version (version_num VARCHAR(32) NOT NULL)"))
        conn.execute(text("INSERT INTO zz_alembic_version VALUES ('0001')"))
    assert "notes" not in {c["name"] for c in inspect(engine).get_columns("zz_versions")}
    assert upgrade(engine, "zz_") == "alembic"
    assert "notes" in {c["name"] for c in inspect(engine).get_columns("zz_versions")}
    assert upgrade(engine, "zz_") == "alembic"  # idempotent
    with engine.begin() as conn:
        assert conn.execute(text("SELECT version_num FROM zz_alembic_version")).scalar() == "0002"
    # tables created by create_all without alembic get stamped and upgraded too
    url2 = f"sqlite:///{tmp_path}/plain.db"
    e2 = create_engine(url2)
    build_tables("zz_").metadata.create_all(e2)
    assert upgrade(e2, "zz_") == "alembic"
    with e2.begin() as conn:
        assert conn.execute(text("SELECT version_num FROM zz_alembic_version")).scalar() == "0002"
    cfg = Config()
    cfg.set_main_option("script_location", str(HERE))
    assert ScriptDirectory.from_config(cfg).get_current_head() == "0002"


@pytest.mark.skipif(not PYDANTIC_V2, reason="reference is generated with pydantic v2 signatures")
def test_reference_is_up_to_date():
    """docs/reference.md is generated from the code; regenerate with `python docs/gen_reference.py`."""
    import importlib.util

    path = Path(__file__).resolve().parents[1] / "docs" / "gen_reference.py"
    spec = importlib.util.spec_from_file_location("gen_reference", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod.OUT.read_text() == mod.main(), "docs/reference.md is stale: run python docs/gen_reference.py"


def test_docs_command(capsys):
    assert main(["docs"]) == 0
    out = capsys.readouterr().out
    assert "prompt-pivot" in out and "aget" in out and "Do not" in out


def test_skill_file_is_up_to_date():
    """skills/prompt-pivot/SKILL.md is generated; regenerate with `prompt-pivot skill --dir skills`."""
    import promptpivot

    path = Path(__file__).resolve().parents[1] / "skills" / "prompt-pivot" / "SKILL.md"
    assert path.read_text() == promptpivot.agent_skill(), "SKILL.md is stale: run prompt-pivot skill --dir skills"


def test_skill_command(tmp_path, capsys):
    assert main(["skill", "--dir", str(tmp_path)]) == 0
    assert capsys.readouterr().out.startswith("wrote ")
    text = (tmp_path / "prompt-pivot" / "SKILL.md").read_text()
    assert text.startswith("---\nname: prompt-pivot\ndescription: ")
    assert "## Do not" in text
    assert main(["skill", "--print"]) == 0
    assert capsys.readouterr().out == text
