from __future__ import annotations

import json

import pytest

from promptdeck import PromptRegistry
from promptdeck.cli import main
from promptdeck.migrations import upgrade
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
    monkeypatch.delenv("PROMPTDECK_DATABASE_URL", raising=False)
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
