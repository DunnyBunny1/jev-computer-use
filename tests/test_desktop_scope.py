from pathlib import Path

import pytest

from typesafe_computer_use.models import Abort
from typesafe_computer_use.platform_adapter import desktop
from typesafe_computer_use.runner import RunConfig, check_app_scope


def test_app_switch_stops_scoped_native_task(monkeypatch):
    monkeypatch.setattr(desktop, "frontmost_app_and_pid", lambda: ("ChatGPT", 1))
    cfg = RunConfig(goal="type test", out=Path("unused"), require_app="TextEdit")
    with pytest.raises(Abort, match="foreground left TextEdit"):
        check_app_scope(cfg)


def test_expected_app_can_continue(monkeypatch):
    monkeypatch.setattr(desktop, "frontmost_app_and_pid", lambda: ("TextEdit", 1))
    check_app_scope(RunConfig(goal="type test", out=Path("unused"), require_app="TextEdit"))
