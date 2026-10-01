"""Contracts for spatial input and planner text handoff. No live devices."""

import pytest
from test_browser_loop import FakeBrowser, FakeTypeSafe, login_page
from test_browser_offline import StubSession, element_dict, page_dict

from typesafe_computer_use.browser import act
from typesafe_computer_use.browser.decide import available_actions
from typesafe_computer_use.browser.perceive import perceive
from typesafe_computer_use.browser.runner import run_goal


def test_drag_releases_button_after_transport_error(monkeypatch):
    page = perceive(StubSession([page_dict(items=[element_dict(0, draggable=True), element_dict(1, draggable=True, y=60)])]))
    calls = []

    class Broken:
        def call(self, method, params):
            calls.append(params)
            if params["type"] == "mouseMoved" and params.get("buttons") == 1:
                raise RuntimeError("move failed")

    monkeypatch.setattr(act, "element_rect", lambda s, i: dict(x=10, y=20 + i * 40, vw=100, vh=100))
    with pytest.raises(RuntimeError):
        act.drag(Broken(), *page.items)
    assert calls[-1]["type"] == "mouseReleased" and calls[-1]["buttons"] == 0


def test_drag_refuses_covered_endpoints_before_any_input():
    session = StubSession([page_dict(items=[element_dict(0, draggable=True), element_dict(1, draggable=True, covered=True)])])
    page = perceive(session)
    assert "refused" in act.drag(session, *page.items)
    assert not session.calls
    assert "drag" in available_actions(page, allow_type=True, can_write=True)


def test_grid_coordinates_are_computed_from_visible_control_positions():
    items = [element_dict(i, tag="input", role="checkbox", x=10 + 20 * (i % 3), y=20 + 30 * (i // 3)) for i in range(6)]
    page = perceive(StubSession([page_dict(items=items)]))
    assert "[row 1, column 3]" in page.items[2].name
    assert "[row 2, column 1]" in page.items[3].name


def test_planner_binding_preserves_exact_value_without_extra_writer(monkeypatch):
    browser = FakeBrowser(login_page())
    target = perceive(browser).items[0]
    seen = []
    monkeypatch.setattr(act, "type_text", lambda s, i, t: seen.append((i, t)))
    monkeypatch.setattr(act, "press", lambda *a: None)
    monkeypatch.setattr(act, "field_value", lambda *a: "Exact Value")
    monkeypatch.setattr("typesafe_computer_use.browser.runner.verify_typed", lambda *a, **k: 0.99)
    monkeypatch.setattr(act, "observe_until_changed", lambda *a, **k: (perceive(browser), 0, True))
    result = run_goal(
        browser,
        FakeTypeSafe(("type_text", "0")),
        "Fill form",
        writer=object(),
        max_steps=1,
        field_values={target.name: "Exact Value"},
        verbose=False,
    )
    assert seen == [(0, "Exact Value")]
    assert result.steps[0].text_source == "planner_binding"


def test_planner_binding_cannot_bypass_credential_guard(monkeypatch):
    raw = login_page()
    raw["items"][0]["secret"] = True
    browser = FakeBrowser(raw)

    def forbidden(*a, **k):
        raise AssertionError("secret input")

    monkeypatch.setattr(act, "type_text", forbidden)
    target = perceive(browser).items[0]
    result = run_goal(
        browser,
        FakeTypeSafe(("type_text", "0")),
        "Fill form",
        writer=object(),
        max_steps=1,
        field_values={target.name: "anything"},
        verbose=False,
    )
    assert "refused_credential" in result.steps[0].detail


def test_visual_expert_restores_model_after_failure():
    from typesafe_computer_use.writer_fallback import Endpoint, FallbackWriter

    endpoint = Endpoint("openai", object(), "gpt-5.4-mini", "low")
    writer = FallbackWriter([endpoint])
    with pytest.raises(RuntimeError), writer.effort("medium", expert=True):
        assert endpoint.model == "gpt-5.4" and endpoint.reasoning == "medium"
        raise RuntimeError("request failed")
    assert endpoint.model == "gpt-5.4-mini" and endpoint.reasoning == "low"


def test_slider_confidence_uses_actual_slider_not_irrelevant_element():
    from types import SimpleNamespace

    from typesafe_computer_use.browser.decide import Decision

    decision = Decision(
        kind=SimpleNamespace(choice="adjust_slider", confidence=0.99),
        satisfied=None,
        element=SimpleNamespace(choice="0", confidence=0.99),
        answers={"slider": {"choice": "1", "confidence": 0.1}, "adjustment": {"choice": "4", "confidence": 0.9}},
    )
    assert decision.chosen_element == 1 and decision.confidence == 0.1


def test_click_waits_for_hover_replacement_before_press(monkeypatch):
    page = perceive(StubSession([page_dict(items=[element_dict(0)])]))
    initial = dict(x=10, y=20, vw=100, vh=100, hit=True)
    settled = dict(x=14, y=20, vw=100, vh=100, hit=True)
    frames = iter([initial, None, settled, settled])
    monkeypatch.setattr(act, "element_rect", lambda *a: next(frames))
    monkeypatch.setattr(act.time, "sleep", lambda *a: None)
    session = StubSession([])
    act.click(session, 0, page.items[0], page)
    events = [params for method, params in session.calls if method == "Input.dispatchMouseEvent"]
    assert [e["type"] for e in events] == ["mouseMoved", "mouseMoved", "mousePressed", "mouseReleased"]
    assert events[-2]["x"] == 14


def test_readonly_field_cannot_receive_planner_binding(monkeypatch):
    raw = login_page()
    raw["items"][0]["readonly"] = True
    browser = FakeBrowser(raw)

    def forbidden(*a, **k):
        raise AssertionError("typed into readonly field")

    monkeypatch.setattr(act, "type_text", forbidden)
    target = perceive(browser).items[0]
    result = run_goal(
        browser,
        FakeTypeSafe(("type_text", "0")),
        "Fill form",
        writer=object(),
        max_steps=1,
        field_values={target.name: "date"},
        verbose=False,
    )
    assert result.steps[0].text_source != "planner_binding"


def test_small_container_scroll_keeps_overlap():
    page = perceive(StubSession([page_dict(items=[element_dict(0, h=100, scroll_max=300)])]))
    session = StubSession([])
    act.scroll(session, 3, page, page.items[0])
    assert session.calls[-1][1]["deltaY"] == 65
