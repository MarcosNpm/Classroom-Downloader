import json
from pathlib import Path

import pytest

from classroom_dl.config import Config, config_dir, default_token_path
from classroom_dl.errors import ClassroomDLError


def test_config_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    monkeypatch.delenv("CLASSROOM_DL_OUTPUT", raising=False)
    monkeypatch.delenv("CLASSROOM_DL_CREDENTIALS", raising=False)

    config = Config()
    config.output_dir = tmp_path / "descargas"
    config.docs_format = "docx"
    config.sheets_format = "csv"
    config.jobs = 4
    config.save()

    saved = json.loads((config_dir() / "config.json").read_text())
    assert saved["docs_format"] == "docx"

    loaded = Config.load()
    assert loaded.output_dir == tmp_path / "descargas"
    assert loaded.docs_format == "docx"
    assert loaded.sheets_format == "csv"
    assert loaded.jobs == 4


def test_env_overrides_config(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    monkeypatch.setenv("CLASSROOM_DL_OUTPUT", str(tmp_path / "env-out"))
    config = Config.load()
    assert config.output_dir == tmp_path / "env-out"


def test_resolve_credentials_prefers_existing(tmp_path):
    secret = tmp_path / "client_secret.json"
    secret.write_text("{}")
    config = Config(credentials=secret)
    assert config.resolve_credentials() == secret


def test_resolve_credentials_raises_with_hint(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("CLASSROOM_DL_CREDENTIALS", raising=False)
    config = Config()
    with pytest.raises(ClassroomDLError, match="client_secret.json"):
        config.resolve_credentials()


def test_token_path_default(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    config = Config()
    assert config.resolve_token() == Path(default_token_path())


def test_invalid_config_values_are_ignored(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    path = config_dir() / "config.json"
    path.write_text(json.dumps({"docs_format": "exe", "jobs": -2}))
    config = Config.load()
    assert config.docs_format == "pdf"
    assert config.jobs == 2
