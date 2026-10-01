"""Host invariants around the copied loop, without browser or model calls."""

import json
import os
from unittest.mock import Mock

import pytest

from typesafe_computer_use.browser import ultrafast


@pytest.fixture
def isolated_env(monkeypatch):
    monkeypatch.setattr(os, "environ", {})
    return monkeypatch


def test_text_provider_key_stays_with_its_endpoint(isolated_env):
    isolated_env.setenv("OPENROUTER_API_KEY", "router-test-key")
    isolated_env.setenv("OPENAI_API_KEY", "openai-test-key")
    ultrafast.configure_text_model()
    assert os.environ["TEXT_MODEL_API_KEY"] == "router-test-key"
    assert os.environ["TEXT_MODEL_BASE_URL"] == "https://openrouter.ai/api/v1"
    assert os.environ["TEXT_MODEL"] == "inception/mercury-2.5"


def test_explicit_text_configuration_is_preserved(isolated_env):
    isolated_env.setenv("TEXT_MODEL_API_KEY", "explicit-test-key")
    isolated_env.setenv("TEXT_MODEL_BASE_URL", "https://example.test/v1")
    isolated_env.setenv("OPENROUTER_API_KEY", "router-test-key")
    ultrafast.configure_text_model()
    assert os.environ["TEXT_MODEL_BASE_URL"] == "https://example.test/v1"
    assert os.environ["TEXT_MODEL_API_KEY"] == "explicit-test-key"


@pytest.mark.parametrize("state_status,expected", [("done", "done_unverified"), ("blocked", "blocked")])
def test_completion_is_a_claim_not_an_independent_grade(tmp_path, monkeypatch, isolated_env, state_status, expected):
    state = {
        "status": state_status,
        "history": [],
        "decisions": [],
        "text_calls": [],
        "elapsed_ms": 1,
        "page": {"url": "https://example.test/"},
    }
    agent = Mock(state=state, snapshot=Mock(return_value=state))
    monkeypatch.setattr(ultrafast, "Agent", Mock(return_value=agent))
    result = ultrafast.run_ultrafast(object(), "Read the page", output=tmp_path)
    assert result["outcome"] == expected
    assert result["planner_calls"] == 0
    assert "passed" not in json.loads((tmp_path / "task.json").read_text())
    agent.command.assert_not_called()
    agent.close.assert_called_once()
