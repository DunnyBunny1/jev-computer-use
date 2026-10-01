"""Offline contracts for a dynamic operation/target policy. No paid APIs."""

import asyncio
import json
import time
from copy import deepcopy
from unittest.mock import Mock

import pytest

from typesafe_computer_use._vendor.jev_ultrafast import agent as loop
from typesafe_computer_use._vendor.jev_ultrafast import model
from typesafe_computer_use._vendor.jev_ultrafast.browser import StalePage, browser_operation, fingerprint


def page():
    state = {
        "url": "https://example.test/",
        "title": "Search",
        "text": "Search",
        "scroll": {"y": 0},
        "actions": [
            {"id": "e1", "kind": "fill", "label": "Search", "role": "textbox", "value": "", "node": 10},
            {"id": "e2", "kind": "click", "label": "Open Search", "role": "textbox", "value": "", "node": 10},
            {"id": "e3", "kind": "click", "label": "Go", "role": "button", "value": "", "node": 20},
            {"id": "wait", "kind": "wait", "label": "Wait"},
        ],
    }
    state["fingerprint"] = fingerprint(state)
    return state


def choice(ids, selected):
    return {"choice": selected, "confidence": 1.0, "probabilities": {i: float(i == selected) for i in ids}}


def decision(action="e1"):
    return {
        "choice": action,
        "operation": "TYPE_TEXT",
        "target": "1",
        "confidence": 1.0,
        "probabilities": {action: 1.0},
        "latency_ms": 10,
        "usage": {},
    }


@pytest.mark.parametrize("mutation", ["unknown", "nan", "missing", "negative", "non_max", "confidence"])
def test_invalid_choice_is_rejected(mutation):
    a = choice(["a", "b"], "a")
    if mutation == "unknown":
        a["choice"] = "invented"
    elif mutation == "nan":
        a["probabilities"]["a"] = float("nan")
    elif mutation == "missing":
        del a["probabilities"]["b"]
    elif mutation == "negative":
        a["probabilities"]["b"] = -1
    elif mutation == "non_max":
        a["choice"] = "b"
    else:
        a["confidence"] = 5
    with pytest.raises(ValueError, match="Invalid TypeSafe"):
        model.validate_choice(a, {"a", "b"})


def test_one_index_per_node_with_operation_specific_targets():
    elements, targets, controls = model.action_space(page()["actions"])
    assert len(elements) == 2
    assert elements[0]["operations"] == ["TYPE_TEXT", "CLICK"]
    assert targets["TYPE_TEXT"]["1"]["id"] == "e1"
    assert targets["CLICK"]["1"]["id"] == "e2"
    assert targets["CLICK"]["2"]["id"] == "e3"
    assert "WAIT" in controls


def test_all_heads_are_one_request_and_only_matching_head_executes(monkeypatch):
    calls = []

    def post(_url, _key, body):
        calls.append(body)
        return {
            "model": "test",
            "answers": {
                "operation": choice(body["questions"]["operation"]["criteria"], "TYPE_TEXT"),
                "type_text_target": choice(["1"], "1"),
                "click_target": {"choice": "invented"},
            },
        }

    monkeypatch.setenv("TYPESAFE_API_KEY", "test")
    monkeypatch.setattr(model, "post_json", post)
    d = model.choose(page(), "Find a book", [])
    assert len(calls) == 1
    assert d["operation"] == "TYPE_TEXT" and d["target"] == "1" and d["choice"] == "e1"
    assert set(calls[0]["questions"]) == {"operation", "click_target", "type_text_target"}


def test_click_cannot_consume_a_text_target(monkeypatch):
    def post(_url, _key, body):
        return {
            "model": "test",
            "answers": {
                "operation": choice(body["questions"]["operation"]["criteria"], "CLICK"),
                "type_text_target": choice(["1"], "1"),
                "click_target": choice(["1", "2", "999"], "999"),
            },
        }

    monkeypatch.setenv("TYPESAFE_API_KEY", "test")
    monkeypatch.setattr(model, "post_json", post)
    with pytest.raises(ValueError, match="Invalid TypeSafe"):
        model.choose(page(), "Find a book", [])


def test_target_head_receives_control_state_and_full_next_step_rules(monkeypatch):
    p = page()
    p["actions"].insert(
        0,
        {
            "id": "toggle",
            "kind": "click",
            "label": "Free cancellation",
            "node": 30,
            "role": "checkbox",
            "checked": "true",
            "selected": False,
        },
    )

    def post(_url, _key, body):
        questions = body["questions"]
        target = questions["click_target"]
        assert target["criteria"]["1"]["checked"] == "true"
        assert target["criteria"]["1"]["selected"] is False
        assert questions["operation"]["instructions"]["rules"] in target["instructions"]["rules"]
        return {
            "model": "test",
            "answers": {
                "operation": choice(questions["operation"]["criteria"], "CLICK"),
                "click_target": choice(target["criteria"], "3"),
            },
        }

    monkeypatch.setenv("TYPESAFE_API_KEY", "test")
    monkeypatch.setattr(model, "post_json", post)
    d = model.choose(p, "Search with free cancellation", [])
    assert d["choice"] == "e3"


def test_quoted_task_text_still_uses_the_llm(monkeypatch):
    monkeypatch.setenv("TEXT_MODEL_API_KEY", "test")
    post = Mock(return_value={"choices": [{"message": {"content": '{"text":"Zurich"}'}}]})
    monkeypatch.setattr(model, "post_json", post)
    context = model.field_context('Fly from "Zurich" to London', page()["actions"][0], page(), [])
    assert model.field_text(context)[0] == "Zurich"
    assert post.call_count == 1
    sent = json.loads(post.call_args.args[2]["messages"][1]["content"])
    assert sent["goal"] == 'Fly from "Zurich" to London'


def test_missing_text_credential_stops_before_guessing(monkeypatch):
    monkeypatch.delenv("TEXT_MODEL_API_KEY", raising=False)
    with pytest.raises(ValueError, match="TEXT_MODEL_API_KEY"):
        model.field_text({"goal": 'Enter "Zurich"'})


@pytest.fixture
def runner():
    a = loop.Agent.__new__(loop.Agent)
    a.external_recovery = False
    a.screenshots = False
    a.pending_text = None
    p = page()
    a.state = {
        "browser": Mock(fresh=Mock(return_value=True), observe=Mock(return_value=p)),
        "page": p,
        "decision": decision(),
        "goal": "Find a book",
        "history": [],
        "decisions": [],
        "status": "predicted",
        "started_at": time.perf_counter(),
        "record": False,
        "text_calls": [],
    }
    return a


def test_stale_decision_is_consumed_before_any_mutation(runner):
    runner.state["browser"].fresh.return_value = False
    with pytest.raises(StalePage):
        runner.command("act", {"fingerprint": runner.state["page"]["fingerprint"]})
    runner.state["browser"].act.assert_not_called()
    assert runner.state["decision"] is None


def test_generated_text_reused_only_for_identical_retry_context(runner, monkeypatch):
    helper = Mock(return_value=("book", {"model": "test", "latency_ms": 10}))
    monkeypatch.setattr(loop, "field_text", helper)
    runner.state["browser"].act.side_effect = [StalePage("Changed before input"), None]
    with pytest.raises(StalePage):
        runner.command("act", {"fingerprint": runner.state["page"]["fingerprint"]})
    runner.state["decision"] = decision()
    runner.command("act", {"fingerprint": runner.state["page"]["fingerprint"]})
    assert helper.call_count == 1
    assert runner.state["browser"].act.call_count == 2  # The first call rejects before any browser input.
    assert runner.pending_text is None


def test_changed_field_context_does_not_reuse_generated_text(runner, monkeypatch):
    helper = Mock(return_value=("book", {"model": "test", "latency_ms": 10}))
    monkeypatch.setattr(loop, "field_text", helper)
    runner.state["browser"].act.side_effect = [StalePage("Changed before input"), None]
    with pytest.raises(StalePage):
        runner.command("act", {"fingerprint": runner.state["page"]["fingerprint"]})
    runner.state["page"]["text"] = "Different page context"
    runner.state["decision"] = decision()
    runner.command("act", {"fingerprint": runner.state["page"]["fingerprint"]})
    assert helper.call_count == 2


def test_loading_waits_do_not_trigger_no_progress_stop(runner):
    for _ in range(5):
        runner.state["decision"] = decision("wait")
        runner.command("act", {"fingerprint": runner.state["page"]["fingerprint"]})
    assert len(runner.state["history"]) == 5 and runner.state["status"] == "ready"


def test_stale_observation_preserves_executed_action(runner):
    runner.state["decision"] = decision("e3")
    runner.state["browser"].observe.side_effect = StalePage("changed")
    with pytest.raises(StalePage):
        runner.command("act", {"fingerprint": runner.state["page"]["fingerprint"]})
    assert runner.state["history"][-1]["action"] == "Go"
    runner.state["browser"].act.assert_called_once()


def test_observation_is_one_atomic_browser_read(monkeypatch):

    p = page()
    cdp = Mock(return_value={"result": {"value": p}})
    actual = browser_operation({"operation": "observe", "session": Mock(call=cdp), "screenshot": False})
    assert actual["actions"] == p["actions"]
    assert cdp.call_count == 1
    assert cdp.call_args.args[0] == "Runtime.evaluate"


def test_executor_rejects_a_stale_page_before_browser_input(monkeypatch):
    import typesafe_computer_use._vendor.jev_ultrafast.browser as browser

    b = browser.Browser.__new__(browser.Browser)
    b.fresh = Mock(return_value=False)
    operation = Mock()
    monkeypatch.setattr(browser, "browser_operation", operation)
    with pytest.raises(StalePage):
        b.act(page()["actions"][0], page(), "book")
    operation.assert_not_called()


@pytest.mark.parametrize("response", [{"exceptionDetails": {}}, {"result": {}}])
def test_interrupted_dropdown_mutation_cannot_be_retried_as_stale(monkeypatch, response):

    # A navigation can destroy the evaluation result after the change event already fired.
    if "exceptionDetails" in response:
        response["exceptionDetails"] = {"text": "Execution context destroyed"}
    cdp = Mock(return_value=response)
    with pytest.raises(RuntimeError, match="Dropdown execution"):
        browser_operation(
            {
                "operation": "act",
                "session": Mock(call=cdp),
                "action": {
                    "id": "e1",
                    "kind": "select",
                    "node": 1,
                    "value": "Design",
                },
            }
        )
    assert cdp.call_count == 1


def test_fingerprint_tracks_values_and_identity_not_screenshots():
    p = page()
    other = deepcopy(p)
    other["screenshot"] = "changed"
    assert fingerprint(p) == fingerprint(other)
    other["actions"][0]["node"] = 99
    assert fingerprint(p) != fingerprint(other)


@pytest.mark.parametrize("content", ["Thinking: Zurich", '{"text":null}', '{"text":"Zurich","extra":true}', '{"text":123}'])
def test_text_helper_rejects_invalid_values(monkeypatch, content):
    monkeypatch.setenv("TEXT_MODEL_API_KEY", "test")
    monkeypatch.setattr(model, "post_json", Mock(return_value={"choices": [{"message": {"content": content}}]}))
    with pytest.raises(ValueError, match="nothing typed"):
        model.field_text({"goal": "Find a flight"})


def test_navigation_during_prediction_reobserves_without_action(runner):
    runner.state["browser"].fresh.side_effect = StalePage("Document navigating")
    runner.command("tick")
    assert runner.state["status"] == "ready"
    assert runner.state["decision"] is None
    runner.state["browser"].act.assert_not_called()


def test_text_writer_receives_other_observed_field_values():
    p = page()
    p["actions"].append(
        {"id": "source", "node": 30, "kind": "fill", "role": "textbox", "label": "Source", "value": "amber cedar"}
    )
    context = model.field_context("Copy the final word into Search", p["actions"][0], p, [])
    assert any(f["value"] == "amber cedar" for f in context["fields"])


def test_done_claim_is_audited_before_it_can_stop_the_agent(runner, monkeypatch):
    runner.state["status"] = "ready"
    monkeypatch.setattr(loop, "choose", Mock(return_value=decision("DONE")))
    audit = Mock(return_value=decision("e3"))
    monkeypatch.setattr(loop, "review_completion", audit)
    runner.command("tick")
    audit.assert_called_once()
    assert runner.state["history"][-1]["action"] == "Go"
    assert runner.state["status"] == "ready"
    assert len(runner.state["decisions"]) == 2


def test_completion_review_cannot_invent_an_action(monkeypatch):
    monkeypatch.setenv("TYPESAFE_API_KEY", "test")
    monkeypatch.setattr(model, "post_json", Mock(return_value={"answers": {"remaining_action": choice(["fake"], "fake")}}))
    with pytest.raises(ValueError, match="Invalid TypeSafe"):
        model.review_completion(page(), "Fill the form", [])


def test_network_deadline_cancels_a_provider_that_keeps_streaming(monkeypatch):
    cancelled = []

    async def streaming(*args, **kwargs):
        try:
            while True:
                await asyncio.sleep(0.001)
        finally:
            cancelled.append(True)

    monkeypatch.setattr(model.CLIENT, "post", streaming)
    monkeypatch.setattr(model, "REQUEST_SECONDS", 0.02)
    started = time.perf_counter()
    with pytest.raises(RuntimeError, match="Model connection failed"):
        model.post_json("https://example.test", "unused", {})
    assert cancelled == [True]
    assert time.perf_counter() - started < 1


def test_failed_text_provider_falls_back_before_any_input_and_keeps_keys_bound(monkeypatch):
    monkeypatch.setattr(
        model.os,
        "environ",
        {
            "TEXT_MODEL_API_KEY": "router-key",
            "TEXT_MODEL_BASE_URL": "https://openrouter.ai/api/v1",
            "TEXT_MODEL": "inception/mercury-2.5",
            "OPENAI_API_KEY": "openai-key",
            "TEXT_MODEL_FALLBACKS": "openai",
        },
    )
    calls = []

    def post(url, key, body):
        calls.append((url, key, body["model"]))
        if len(calls) == 1:
            raise RuntimeError("Model connection failed")
        return {"choices": [{"message": {"content": '{"text":"cedar"}'}}]}

    monkeypatch.setattr(model, "post_json", post)
    value, helper = model.field_text({"goal": "Enter cedar"})
    assert value == "cedar"
    assert calls == [
        ("https://openrouter.ai/api/v1/chat/completions", "router-key", "inception/mercury-2.5"),
        ("https://api.openai.com/v1/chat/completions", "openai-key", "gpt-4.1-nano"),
    ]
    assert helper["model"] == "gpt-4.1-nano" and len(helper["prior_failures"]) == 1


def test_observed_ordinal_constraint_overrides_incorrect_recovery_hint():
    p = page()
    p["actions"] = [
        {"id": "wrong", "pagination": {"ordinal_from_observed_pages": 4}},
        {"id": "right", "pagination": {"ordinal_from_observed_pages": 8}},
        {"id": "uncertain", "pagination": {"ordinal_if_uniform_pages": 4}},
        {"id": "next"},
    ]
    allowed = model.eligible_actions(p, "Open the 8th search result.\nNext-step guidance: Click wrong.")
    assert [a["id"] for a in allowed] == ["right", "uncertain", "next"]
    # Multiple requested ordinals and an inferred uniform page size cannot justify pruning.
    assert model.eligible_actions(p, "Compare the 4th result and 8th result") == p["actions"]


def test_completion_review_preserves_checked_and_selected_state(monkeypatch):
    p = page()
    p["actions"][2].update(role="checkbox", checked="true", selected="false", expanded="true", current_value="yes")

    def post(_url, _key, body):
        criteria = body["questions"]["remaining_action"]["criteria"]
        for key in ("role", "checked", "selected", "expanded", "current_value"):
            assert criteria["e3"][key] == p["actions"][2][key]
        return {"model": "test", "answers": {"remaining_action": choice(criteria, "DONE")}}

    monkeypatch.setenv("TYPESAFE_API_KEY", "test")
    monkeypatch.setattr(model, "post_json", post)
    assert model.review_completion(p, "Keep the option checked", [])["choice"] == "DONE"


@pytest.mark.parametrize("terminal", ["DONE", "BLOCKED"])
def test_terminal_choice_does_not_require_optional_recovery(runner, monkeypatch, terminal):
    runner.state["history"] = [{"action": "Go", "page_changed": False}] * 4
    monkeypatch.setattr(loop, "choose", Mock(return_value=decision(terminal)))
    monkeypatch.setattr(loop, "review_completion", Mock(return_value=decision(terminal)))
    recovery = Mock(side_effect=AssertionError("No recovery for terminal choices"))
    monkeypatch.setattr(loop, "recovery_focus", recovery)
    runner.command("predict")
    assert runner.state["decision"]["choice"] == terminal
    recovery.assert_not_called()


@pytest.mark.parametrize("error", [ValueError("missing key"), RuntimeError("providers unavailable"), None])
def test_optional_recovery_unavailable_preserves_jev_choice(runner, monkeypatch, error):
    runner.state["history"] = [{"action": "Go", "page_changed": False}] * 4
    monkeypatch.setattr(loop, "choose", Mock(return_value=decision("e3")))
    monkeypatch.setattr(loop, "recovery_focus", Mock(side_effect=error, return_value=(None, {"model": "test"})))
    runner.command("predict")
    assert runner.state["decision"]["choice"] == "e3"
    assert len(runner.state["recovery_calls"]) == 1


def test_recovery_accepts_null_without_fallback(monkeypatch):
    monkeypatch.setenv("TEXT_MODEL_API_KEY", "test")
    post = Mock(return_value={"choices": [{"message": {"content": '{"text":null}'}}]})
    monkeypatch.setattr(model, "post_json", post)
    assert model.recovery_focus(page(), "Nothing more to do", [])[0] is None
    assert post.call_count == 1
