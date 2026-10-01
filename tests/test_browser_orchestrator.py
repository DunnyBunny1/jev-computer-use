"""Offline planner/actor contracts; no real browser, models or desktop."""

from types import SimpleNamespace

import pytest
from test_browser_loop import FakeBrowser, FakeTypeSafe, FakeWriter, login_page

from typesafe_computer_use.browser import act, orchestrator
from typesafe_computer_use.browser.decide import base_state
from typesafe_computer_use.browser.perceive import perceive
from typesafe_computer_use.browser.runner import run_goal
from typesafe_computer_use.writer import WriterError


def plan(status="continue", **kw):
    return orchestrator.Plan(status, "Click Submit", "Submit is visible", "Remember task facts", "", **kw)


def setup_loop(monkeypatch, tmp_path, plans):
    browser = FakeBrowser(login_page())
    seen = []

    def planner(*args):
        seen.append(args)
        return plans.pop(0)

    monkeypatch.setattr(orchestrator, "plan_task", planner)
    return browser, seen, dict(writer=None, planner=None, output=tmp_path, vision=False)


def test_budget_and_planner_history_span_segments_actor_history_stays_local(monkeypatch, tmp_path):
    browser, seen, args = setup_loop(monkeypatch, tmp_path, [plan(), plan()])
    segments = []

    def segment(*pos, **kw):
        segments.append(kw)
        return SimpleNamespace(
            outcome="max_steps",
            steps=[SimpleNamespace(action="click", detail="clicked") for _ in range(kw["max_steps"])],
            url_after="https://example.test",
        )

    monkeypatch.setattr(orchestrator, "run_goal", segment)
    result = orchestrator.run_task(browser, None, "test", max_steps=3, segment_steps=2, **args)
    assert result["outcome"] == "step_budget" and result["steps"] == 3
    assert [s["max_steps"] for s in segments] == [2, 1]
    assert segments[1]["initial_history"] == []
    assert seen[1][3][0]["actions"] == ["click: clicked", "click: clicked"]
    assert segments[0]["verify_completion"] is False
    assert (tmp_path / "task.json").exists()


def test_external_termination_does_not_call_planner_or_actor(monkeypatch, tmp_path):
    browser, seen, args = setup_loop(monkeypatch, tmp_path, [])
    result = orchestrator.run_task(browser, None, "test", stop_when=lambda: True, **args)
    assert result["outcome"] == "environment_terminated" and not seen


def test_changed_page_defers_final_completion(monkeypatch, tmp_path):
    browser, seen, args = setup_loop(monkeypatch, tmp_path, [plan("complete"), plan("blocked")])
    monkeypatch.setattr(act, "observe_until_changed", lambda *a, **kw: (perceive(browser), 1, True))
    result = orchestrator.run_task(browser, FakeTypeSafe(), "test", **args)
    assert result["outcome"] == "blocked"
    assert result["segments"][0]["outcome"] == "completion_deferred"
    assert len(seen) == 2


def test_subtask_handoff_does_not_wait_for_a_page_timer(monkeypatch):
    browser = FakeBrowser(login_page())

    def never(*a, **kw):
        raise AssertionError("Subtask completion is verified by planner")

    monkeypatch.setattr(act, "observe_until_changed", never)
    result = run_goal(browser, FakeTypeSafe(), "test", verify_completion=False, verbose=False)
    assert result.outcome == "done"


@pytest.mark.parametrize(
    "reply",
    [
        dict(status="unknown", focus="x", evidence="x", notes="", answer=""),
        dict(status="continue", focus="", evidence="x", notes="", answer=""),
        dict(status="complete", focus="", evidence="", notes="", answer=""),
    ],
)
def test_invalid_plans_never_become_actions(reply):
    with pytest.raises(WriterError):
        orchestrator.plan_task(FakeWriter(reply), "test", perceive(FakeBrowser(login_page())), [], "")


def test_scroll_end_is_a_computed_fact():
    raw = login_page()
    raw["items"][0].update(scroll_y=345, scroll_max=345)
    state = base_state("test", perceive(FakeBrowser(raw)), [], url_catalog=None)
    assert state["elements"][0]["scroll"]["at_bottom"] is True


def test_disabled_dropdown_option_is_never_sent_to_browser():
    raw = login_page()
    raw["items"][0].update(options=[dict(index=0, disabled=True, label="Unavailable")])
    browser = FakeBrowser(raw)
    result = act.select_option(browser, perceive(browser).items[0], 0)
    assert "refused" in result and not browser.inputs


def test_pending_action_cannot_be_accepted_as_completion():
    reply = dict(status="complete", focus="Click Submit", evidence="Button ready", notes="", answer="Finished")
    result = orchestrator.plan_task(FakeWriter(reply), "Submit the form", perceive(FakeBrowser(login_page())), [], "")
    assert result.status == "continue" and result.focus == "Click Submit"


def test_new_results_return_to_planner_before_actor_can_guess(monkeypatch):
    browser = FakeBrowser(login_page())
    before = perceive(browser)
    updated = login_page()
    from test_browser_loop import item

    updated["items"] += [item(3, "Result A", tag="a"), item(4, "Result B", tag="a")]
    after = perceive(FakeBrowser(updated))
    monkeypatch.setattr(act, "click", lambda *a: "clicked Search")
    monkeypatch.setattr(act, "observe_until_changed", lambda *a, **kw: (after, 1, True))
    client = FakeTypeSafe(("click", "2"), ("click", "3"))
    result = run_goal(browser, client, "Search", yield_on_new_controls=True, verbose=False)
    assert result.outcome == "scene_changed" and len(result.steps) == 1
    assert len(client.requests) == 1 and before.url == after.url


def test_unchanged_scene_requests_recovery_then_stops_bounded(monkeypatch, tmp_path):
    browser, _seen, args = setup_loop(monkeypatch, tmp_path, [plan() for _ in range(4)])
    notes = []

    def planner(*args):
        notes.append(args[4])
        return plan()

    monkeypatch.setattr(orchestrator, "plan_task", planner)
    monkeypatch.setattr(
        orchestrator,
        "run_goal",
        lambda *a, **kw: SimpleNamespace(
            outcome="done", steps=[SimpleNamespace(action="click", detail="Search")], url_after="https://example.test"
        ),
    )
    result = orchestrator.run_task(browser, None, "find documentation", max_steps=40, **args)
    assert result["outcome"] == "stalled" and result["steps"] == 4
    assert "Recovery:" not in notes[0] and "broaden a failed search" in notes[2]


def test_changed_confirmed_field_values_are_progress(monkeypatch, tmp_path):
    browser, _seen, args = setup_loop(monkeypatch, tmp_path, [plan() for _ in range(6)])
    original = orchestrator.perceive
    count = 0

    def changing(session):
        nonlocal count
        count += 1
        page = original(session)
        from dataclasses import replace

        page.items[0] = replace(page.items[0], written_value=str(count))
        return page

    monkeypatch.setattr(orchestrator, "perceive", changing)
    monkeypatch.setattr(
        orchestrator,
        "run_goal",
        lambda *a, **kw: SimpleNamespace(
            outcome="done", steps=[SimpleNamespace(action="type_text", detail="changed field")], url_after="https://example.test"
        ),
    )
    result = orchestrator.run_task(browser, None, "fill form", max_steps=6, **args)
    assert result["outcome"] == "step_budget" and result["steps"] == 6
