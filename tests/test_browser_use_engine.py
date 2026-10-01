"""Offline boundary checks for the isolated upstream browser runtime."""

from types import SimpleNamespace

import pytest

from typesafe_computer_use.browser import browser_use_engine as engine
from typesafe_computer_use.browser.browser_use_policy import observed_choices, valid_choice


class Node:
    node_name = "INPUT"

    def __init__(self, **attrs):
        self.attributes = attrs

    def get_all_children_text(self, max_depth):
        return ""


def test_choices_never_offer_password_file_hidden_or_disabled():
    nodes = {i: Node(type=kind) for i, kind in enumerate(["password", "file", "hidden", "text", "checkbox"])}
    nodes[5] = Node(type="text", disabled="")
    nodes[6] = Node(type="text", readonly="")
    choices = observed_choices(nodes)
    assert not any(key in choices for key in ["click_0", "click_1", "click_2", "click_5"])
    assert "input_3" in choices and "click_4" in choices
    assert "input_4" not in choices and "input_6" not in choices


@pytest.mark.parametrize(
    "answer",
    [
        {"choice": "unknown", "confidence": 1, "probabilities": {"a": 1}},
        {"choice": "a", "confidence": float("nan"), "probabilities": {"a": 1}},
        {"choice": "a", "confidence": 1, "probabilities": {"a": 0.2}},
        {"choice": "a", "confidence": True, "probabilities": {"a": 1}},
        {"choice": "a", "confidence": 1, "probabilities": {"a": 1, "extra": 0}},
        {"choice": "a", "confidence": 1, "probabilities": None},
    ],
)
def test_malformed_classifier_reply_cannot_execute(answer):
    assert not valid_choice(answer, {"a": "Observed button"})


def test_valid_classifier_reply():
    assert valid_choice({"choice": "a", "confidence": 0.9, "probabilities": {"a": 0.9, "b": 0.1}}, {"a": "A", "b": "B"})


def session():
    return SimpleNamespace(
        ws_url="ws://127.0.0.1:1234/devtools/page/1",
        evaluate=lambda script: "https://example.com" if script == "location.href" else {"width": 800, "height": 600},
    )


def test_remaining_actions_and_cleanup_on_budget(monkeypatch, tmp_path):
    sent = []
    closed = []

    class Worker:
        def __init__(self, config, output, timeout):
            assert timeout == 10

        def send(self, message):
            sent.append(message)

        def receive(self, timeout):
            return {"actions": [{"click": {"index": 1}}]}

        def close(self):
            closed.append(True)

    monkeypatch.setattr(engine, "Worker", Worker)
    result = engine.run_browser_use(session(), "Click", output=tmp_path, max_steps=2, max_seconds=10)
    assert result["outcome"] == "step_budget"
    assert [m["remaining_actions"] for m in sent] == [2, 1]
    assert closed == [True]


def test_stop_callback_does_not_enter_worker_or_prompt(monkeypatch, tmp_path):
    class Worker:
        def __init__(self, config, output, timeout):
            assert "stop_when" not in config

        def send(self, message):
            raise AssertionError("Already terminated")

        def close(self):
            pass

    monkeypatch.setattr(engine, "Worker", Worker)
    result = engine.run_browser_use(session(), "Click", output=tmp_path, stop_when=lambda: True)
    assert result["steps"] == 0 and result["outcome"] == "environment_terminated"


def test_timeout_stops_without_replaying_action(monkeypatch, tmp_path):
    closed = []

    class Worker:
        def __init__(self, *args):
            pass

        def send(self, message):
            pass

        def receive(self, timeout):
            raise TimeoutError()

        def close(self):
            closed.append(True)

    monkeypatch.setattr(engine, "Worker", Worker)
    result = engine.run_browser_use(session(), "Click", output=tmp_path)
    assert result["outcome"] == "time_budget" and closed == [True]


def test_unselected_remote_browser_rejected(tmp_path):
    target = session()
    target.ws_url = "ws://example.com:9222/devtools/page/1"
    with pytest.raises(ValueError, match="explicitly selected"):
        engine.run_browser_use(target, "Click", output=tmp_path)


def test_cache_compatibility_preserves_content_and_other_nulls():
    from typesafe_computer_use.browser.browser_use_policy import omit_empty_cache_control

    original = {
        "messages": [{"content": [{"text": "Keep this", "cache_control": None, "other": None}]}],
        "cache_control": {"type": "ephemeral"},
    }
    result = omit_empty_cache_control(original)
    assert result["messages"][0]["content"] == [{"text": "Keep this", "other": None}]
    assert result["cache_control"] == {"type": "ephemeral"}
    assert "cache_control" in original["messages"][0]["content"][0]


def test_accessibility_name_identifies_unlabelled_input():
    node = Node(type="text", name="surname")
    node.ax_node = SimpleNamespace(name="Last name", properties=[])
    _action, target = observed_choices({8: node})["input_8"]
    assert target["label"] == "Last name" and target["index"] == 8
    assert target["attributes"]["name"] == "surname"


@pytest.mark.parametrize("seconds", [float("nan"), float("inf"), 0, -1])
def test_invalid_deadline_rejected_before_launch(tmp_path, seconds):
    with pytest.raises(ValueError):
        engine.run_browser_use(session(), "Click", output=tmp_path, max_seconds=seconds)


@pytest.mark.parametrize("value", [True, "True", "true", "", None, "unknown"])
def test_password_guard_matches_upstream_boolean_strings(value):
    from typesafe_computer_use.browser.browser_use_policy import keyboard_requires_user

    assert keyboard_requires_user(value)


@pytest.mark.parametrize("value", [False, "False", "false"])
def test_known_safe_focus_allows_keyboard(value):
    from typesafe_computer_use.browser.browser_use_policy import keyboard_requires_user

    assert not keyboard_requires_user(value)


@pytest.mark.parametrize(
    "url",
    [
        "file://localhost/etc/hosts",
        "javascript://example.com/%0Aalert(1)",
        "data:text/html,x",
        "chrome://settings",
        "https://user:secret@example.com",
        "https://[invalid",
    ],
)
def test_nonweb_navigation_rejected(url):
    from typesafe_computer_use.browser.browser_use_policy import permitted_navigation

    assert not permitted_navigation(url)


def test_model_failover_is_inference_only_and_sticky():
    import asyncio

    from typesafe_computer_use.browser.browser_use_models import ModelChain

    calls = []

    class Model:
        provider = "mock"

        def __init__(self, model, status=None):
            self.model, self.status = model, status

        async def ainvoke(self, messages, **kwargs):
            calls.append(self.model)
            if self.status:
                exc = RuntimeError("unfunded")
                exc.status_code = self.status
                raise exc
            return "inference result"

    chain = ModelChain([Model("empty", 402), Model("funded")])
    assert asyncio.run(chain.ainvoke([])) == "inference result"
    assert asyncio.run(chain.ainvoke([])) == "inference result"
    assert calls == ["empty", "funded", "funded"]
    assert chain.failovers == [{"model": "empty", "status": 402}]


def test_nonfunding_error_does_not_rotate_models():
    import asyncio

    from typesafe_computer_use.browser.browser_use_models import ModelChain

    class Model:
        model = "malformed"

        async def ainvoke(self, *args, **kwargs):
            raise ValueError("Malformed action response")

    chain = ModelChain([Model(), object()])
    with pytest.raises(ValueError, match="Malformed"):
        asyncio.run(chain.ainvoke([]))
    assert chain.index == 0


def test_closed_original_tab_cannot_mask_worker_timeout(monkeypatch, tmp_path):
    class Worker:
        def __init__(self, *args):
            pass

        def send(self, message):
            pass

        def receive(self, timeout):
            raise TimeoutError()

        def close(self):
            pass

    target = session()
    original = target.evaluate
    reads = []

    def evaluate(script):
        reads.append(script)
        if reads.count("location.href") > 1:
            raise RuntimeError("Target closed")
        return original(script)

    target.evaluate = evaluate
    monkeypatch.setattr(engine, "Worker", Worker)
    result = engine.run_browser_use(target, "Open tab", output=tmp_path)
    assert result["outcome"] == "time_budget"
    assert (tmp_path / "task.json").is_file()


def test_benchmark_rejects_same_document_episode_restart():
    from bench.run_miniwob import EpisodeGuard

    state = {"start": 100, "episode": 0, "done": False}
    target = SimpleNamespace(
        call=lambda method: {"frameTree": {"frame": {"loaderId": "same"}}},
        evaluate=lambda script: (
            state["start"] if script == "core.ept0" else state["episode"] if script == "WOB_EPISODE_ID" else state.copy()
        ),
    )
    guard = EpisodeGuard(target)
    assert not guard.ended()
    state.update(start=200, episode=1, done=False)
    assert guard.ended() and guard.reset


def test_one_pixel_hidden_proxy_not_offered_as_a_click_target():
    node = Node(type="text")
    node.absolute_position = SimpleNamespace(width=1, height=1)
    assert "click_4" not in observed_choices({4: node})
    node.absolute_position = SimpleNamespace(width=100, height=24)
    assert "click_4" in observed_choices({4: node})


@pytest.mark.skipif(engine.os.name != "posix", reason="POSIX process groups")
def test_timeout_cleanup_terminates_only_owned_process_group(monkeypatch):
    import io
    import signal
    import subprocess

    signals = []
    waits = []

    def wait(timeout=None):
        waits.append(timeout)
        if len(waits) < 3:
            raise subprocess.TimeoutExpired("owned worker", timeout)

    worker = object.__new__(engine.Worker)
    worker.process = SimpleNamespace(pid=43210, poll=lambda: None, wait=wait, stdin=io.StringIO(), stdout=io.StringIO())
    worker.log = io.StringIO()
    monkeypatch.setattr(engine.os, "killpg", lambda pid, sig: signals.append((pid, sig)))
    worker.close()
    assert signals == [(43210, signal.SIGTERM), (43210, signal.SIGKILL)]
    assert worker.log.closed and worker.process.stdin.closed and worker.process.stdout.closed
