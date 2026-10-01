"""Portable setup checks; no UI, network or real credentials."""

import importlib.util
import json
import os
import sys
from pathlib import Path

import pytest

from typesafe_computer_use import computer

ROOT = Path(__file__).resolve().parents[1]


def module(path):
    spec = importlib.util.spec_from_file_location("packaging_helper", path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


@pytest.fixture
def config_home(tmp_path, monkeypatch):
    monkeypatch.setattr(os, "environ", dict(os.environ))
    for name in list(os.environ):
        if name.startswith(("CLICKER_", "COMPUTER_USE_")) or name.endswith("_API_KEY"):
            monkeypatch.delenv(name)
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    engine = tmp_path / "checkout" / "typesafe_computer_use" / "computer.py"
    engine.parent.mkdir(parents=True)
    monkeypatch.setattr(computer, "__file__", str(engine))
    return tmp_path


def test_credentials_precedence_and_legacy_key_only(config_home, monkeypatch):
    home = config_home
    config = home / ".config/jev-computer-use/.env"
    config.parent.mkdir(parents=True)
    config.write_text("OPENAI_API_KEY=user-config\nANTHROPIC_API_KEY=user-anthropic\n")
    (home / "checkout/.env").write_text("OPENAI_API_KEY=checkout\nFIREWORKS_API_KEY=checkout-fireworks\n")
    (home / ".env").write_text("TYPESAFE_API_KEY=legacy-typesafe\nUNRELATED_SECRET=do-not-load\n")
    monkeypatch.setenv("OPENAI_API_KEY", "exported-wins")
    computer.credentials()
    assert os.environ["OPENAI_API_KEY"] == "exported-wins"
    assert os.environ["ANTHROPIC_API_KEY"] == "user-anthropic"
    assert os.environ["FIREWORKS_API_KEY"] == "checkout-fireworks"
    assert os.environ["TYPESAFE_API_KEY"] == "legacy-typesafe"
    assert "UNRELATED_SECRET" not in os.environ


def test_explicit_config_and_missing_home_file(config_home, monkeypatch):
    custom = config_home / "custom.env"
    custom.write_text("TYPESAFE_API_KEY=explicit-key\n")
    monkeypatch.setenv("COMPUTER_USE_ENV_FILE", str(custom))
    computer.credentials()
    assert os.environ["TYPESAFE_API_KEY"] == "explicit-key"
    custom.unlink()
    with pytest.raises(FileNotFoundError, match="COMPUTER_USE_ENV_FILE"):
        computer.credentials()


def test_empty_setup_can_load_without_home_env(config_home):
    computer.credentials()
    assert not os.environ.get("TYPESAFE_API_KEY")


def test_installer_and_wrapper_preserve_existing_skill(tmp_path):
    installer = module(ROOT / "scripts/install_skill.py")
    target = tmp_path / "codex home/skills/computer-use"
    installer.install(target)
    wrapper = module(target / "scripts/run.py")
    assert wrapper.command(["doctor"]) == [sys.executable, "-m", "typesafe_computer_use.computer", "doctor"]
    (target / "user-note").write_text("keep this")
    with pytest.raises(FileExistsError):
        installer.install(target)
    installer.install(target, replace=True)
    backups = list((target.parent.parent / "skill-backups").glob("computer-use-*/user-note"))
    assert len(backups) == 1
    assert backups[0].read_text() == "keep this"
    assert not (target / "user-note").exists()


def test_wrapper_detects_moved_runtime_and_supports_plugin_cli(tmp_path, monkeypatch):
    wrapper = module(ROOT / "skills/computer-use/scripts/run.py")
    fake_script = tmp_path / "scripts/run.py"
    monkeypatch.setattr(wrapper, "__file__", str(fake_script))
    monkeypatch.setattr(wrapper.shutil, "which", lambda _: "/tools/computer-use")
    assert wrapper.command(["doctor"]) == ["/tools/computer-use", "doctor"]
    (tmp_path / ".runtime.json").write_text(json.dumps({"python": str(tmp_path / "missing-python")}))
    with pytest.raises(SystemExit, match="Python moved"):
        wrapper.command(["doctor"])
