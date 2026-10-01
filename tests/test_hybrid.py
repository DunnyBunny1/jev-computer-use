"""Fast/recovery handoff invariants, with no browser or inference calls."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from typesafe_computer_use.browser import hybrid


@pytest.fixture
def world(monkeypatch):
    events = []
    page = {"url": "https://example.test", "fingerprint": "current"}
    state = {"page": page, "status": "ready", "history": [], "decisions": [], "goal": "Fill, adjust slider, submit"}
    choices = iter(
        [
            {"choice": "field", "operation": "TYPE_TEXT"},
            {"choice": "DELEGATE", "operation": "DELEGATE", "recover": "unsupported"},
            {"choice": "submit", "operation": "CLICK"},
            {"choice": "DONE", "operation": "DONE"},
        ]
    )

    def command(name, *args):
        if name == "predict":
            state["decision"] = next(choices)
        else:
            choice = state["decision"]
            events.append(choice["choice"])
            state["status"] = "done" if choice["choice"] == "DONE" else "ready"

    agent = SimpleNamespace(
        state=state,
        command=command,
        browser=SimpleNamespace(observe=lambda **kwargs: page),
        snapshot=lambda: state,
        close=Mock(),
        pending_text=None,
    )
    session = SimpleNamespace(
        call=lambda method: {"targetInfos": []},
        ws_url="ws://127.0.0.1:1234/devtools/page/ABC",
        evaluate=lambda script: page["url"] if script == "location.href" else {"width": 800, "height": 600},
    )
    worker = Mock()

    def receive(*args):
        events.append("repair")
        return {
            "actions": [{"send_keys": {"keys": "End"}}],
            "memory": "slider adjusted",
            "observations": ["Slider at requested value"],
        }

    worker.receive.side_effect = receive
    factory = Mock(return_value=worker)
    monkeypatch.setattr(hybrid, "Worker", factory)
    monkeypatch.setattr(hybrid, "Agent", Mock(return_value=agent))
    monkeypatch.setattr(hybrid, "configure_text_model", lambda: None)
    return SimpleNamespace(session=session, events=events, factory=factory, worker=worker, state=state, agent=agent)


def test_recovery_returns_to_fast_controller_without_replaying_prior_action(world, tmp_path):
    result = hybrid.run_hybrid(world.session, world.state["goal"], output=tmp_path)
    assert world.events == ["field", "repair", "submit", "DONE"]
    assert result["outcome"] == "done_unverified" and result["recovery_steps"] == 1
    world.factory.assert_called_once()
    world.worker.close.assert_called_once()


def test_completed_environment_never_starts_recovery_or_executes(world, tmp_path):
    result = hybrid.run_hybrid(world.session, "Already finished", output=tmp_path, stop_when=lambda: True)
    assert result["outcome"] == "environment_terminated" and world.events == []
    world.factory.assert_not_called()


def test_recovery_timeout_cannot_replay_the_fast_action(world, tmp_path):
    world.worker.receive.side_effect = TimeoutError()
    result = hybrid.run_hybrid(world.session, "Fill then adjust", output=tmp_path)
    assert result["outcome"] == "time_budget" and world.events == ["field"]
    world.worker.close.assert_called_once()


def test_visual_recovery_retains_control_until_explicit_semantic_handoff(world, tmp_path):
    responses = iter(
        [
            {"actions": [{"inspect_region": {"x": 0}}]},
            {"actions": [{"click": {"index": 42}}]},
            {"actions": [{"resume_fast": {"guidance": "Click Submit"}}]},
        ]
    )
    world.worker.receive.side_effect = lambda *args: next(responses)
    result = hybrid.run_hybrid(world.session, "Copy pictured pattern then submit", output=tmp_path)
    assert result["recovery_steps"] == 3
    assert world.events == ["field", "submit", "DONE"]


def test_final_recovery_tab_is_preserved_even_when_done(world, monkeypatch, tmp_path):
    world.worker.receive.side_effect = None
    world.worker.receive.return_value = {
        "done": True,
        "success": True,
        "target_id": "DEF",
        "actions": [{"done": {"text": "Read new tab"}}],
    }
    attached = Mock()
    attached.__enter__ = Mock(return_value=SimpleNamespace())
    attached.__exit__ = Mock(return_value=False)
    monkeypatch.setattr(hybrid, "Session", Mock(return_value=attached))
    result = hybrid.run_hybrid(world.session, "Read new tab", output=tmp_path)
    assert result["target_id"] == "DEF" and result["outcome"] == "done_unverified"


def test_fast_only_work_does_not_start_full_browser_use(world, tmp_path):
    def command(name, *args):
        if name == "predict":
            world.state["decision"] = {"choice": "DONE", "operation": "DONE"}
        else:
            world.state["status"] = "done"

    world.agent.command = command
    result = hybrid.run_hybrid(world.session, "Read visible result", output=tmp_path)
    assert result["outcome"] == "done_unverified"
    world.factory.assert_not_called()


def test_closed_initial_target_restores_shared_request_deadline(world, monkeypatch, tmp_path):
    monkeypatch.setattr(hybrid.model, "DEADLINE", 123)
    world.session.evaluate = Mock(side_effect=RuntimeError("Target closed"))
    result = hybrid.run_hybrid(world.session, "Read", output=tmp_path)
    assert result["outcome"] == "engine_error"
    assert hybrid.model.DEADLINE == 123
    world.factory.assert_not_called()


def test_zero_target_confidence_still_uses_full_recovery(world, monkeypatch, tmp_path):
    original = world.agent.command

    def command(name, *args):
        original(name, *args)
        if name == "predict" and world.state["decision"]["choice"] == "DELEGATE":
            world.state["decision"]["recover"] = "uncertain"

    world.agent.command = command
    monkeypatch.setattr(hybrid.model, "recovery_focus", lambda *args: ("Adjust slider", {}))
    monkeypatch.setattr(
        hybrid.model,
        "choose",
        lambda *args, **kwargs: {"choice": "wrong", "operation": "CLICK", "target_confidence": 0.0, "confidence": 0.99},
    )
    hybrid.run_hybrid(world.session, "Fill adjust submit", output=tmp_path)
    assert world.events == ["field", "repair", "submit", "DONE"]


def test_recovery_context_preserves_errors_and_magnified_images():
    from typesafe_computer_use.browser.browser_use_policy import recovery_results

    error = SimpleNamespace(error="Hidden proxy: use visible trigger")
    picture = SimpleNamespace(images=[{"data": "magnified-pixels"}])
    previous = [error, picture]
    continuation = recovery_results(previous, {"reason": "visual-continuation"}, SimpleNamespace)
    assert continuation is previous
    resumed = recovery_results(previous, {"reason": "uncertain"}, SimpleNamespace)
    assert resumed[:2] == previous and len(resumed) == 3
    assert resumed[1].images[0]["data"] == "magnified-pixels" and previous == [error, picture]
