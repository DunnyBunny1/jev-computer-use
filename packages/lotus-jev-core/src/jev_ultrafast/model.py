"""TypeSafe makes choices; an optional small OpenAI-compatible model writes field values."""

import json
import math
import re
import time

from .questions import NEXT_ACTION, TARGET, TEXT_VALUE

DEADLINE = None
RELAY = None


class FieldValueMissing(RuntimeError):
    """The assignment does not supply a value; a human must provide it."""


def post_json(provider, body):
    if RELAY is None:
        raise RuntimeError("Lotus inference relay is not configured")
    return RELAY(provider, body)


def validate_choice(answer, ids):
    try:
        probabilities = answer["probabilities"]
        numbers = [*probabilities.values(), answer["confidence"]]
        valid = (
            answer["choice"] in ids
            and set(probabilities) == set(ids)
            and all(type(n) in (int, float) and math.isfinite(n) and 0 <= n <= 1 for n in numbers)
            and abs(sum(probabilities.values()) - 1) < 0.02
            and probabilities[answer["choice"]] >= max(probabilities.values()) - 1e-6
        )
    except (KeyError, TypeError, ValueError):
        valid = False
    if not valid:
        raise ValueError("Invalid TypeSafe response; no action executed.")
    return answer


def action_space(actions):
    """One index per observed element; each operation has its own valid target choices."""
    elements, indices, targets, controls = [], {}, {}, {}
    operations = {"click": "CLICK", "fill": "TYPE_TEXT", "select": "SELECT"}
    for action in actions:
        kind = action["kind"]
        if kind not in operations:
            controls[action["id"].upper()] = action
            continue
        node = action["node"]
        if node not in indices:
            index = str(len(elements) + 1)
            indices[node] = index
            element = {
                k: action[k]
                for k in (
                    "role",
                    "value",
                    "checked",
                    "selected",
                    "expanded",
                    "current",
                    "context",
                    "position_in_parent",
                    "group",
                    "pagination",
                    "autocomplete",
                )
                if k in action
            }
            element.update(index=index, label=action["label"].split(" → ")[0], operations=[])
            if kind == "select":
                element["value"] = action.get("current_value", "")
                element["options"] = []
            elements.append(element)
        index = indices[node]
        operation = operations[kind]
        group = targets.setdefault(operation, {})
        element = elements[int(index) - 1]
        if operation not in element["operations"]:
            element["operations"].append(operation)
        target = index
        if kind == "select":
            target = f"{index}:{len(element['options']) + 1}"
            element["options"].append({"index": target, "label": action["label"], "value": action["value"]})
        group[target] = action
    return elements, targets, controls


def eligible_actions(state, goal):
    """Exclude results contradicted by an explicit ordinal and observed preceding pages.

    This uses only the user's numeric constraint and rendered list counts; never a
    benchmark identity, hidden result index, or a model's guessed page-size assumption.
    """
    original = goal.split("\nNext-step guidance:", 1)[0]
    ordinals = {int(n) for n in re.findall(r"\b(\d+)(?:st|nd|rd|th)\s+(?:search\s+)?result\b", original, re.I)}
    if len(ordinals) != 1:
        return state["actions"]
    wanted = next(iter(ordinals))
    return [a for a in state["actions"] if a.get("pagination", {}).get("ordinal_from_observed_pages", wanted) == wanted]


def choose(state, goal, history, *, recovery=False):
    elements, targets, controls = action_space(eligible_actions(state, goal))
    labels = {
        "CLICK": "Click an element, button, menu option, autocomplete suggestion, or calendar day.",
        "TYPE_TEXT": "Enter or replace text in an editable field. A small LLM will supply the value from the goal.",
        "SELECT": "Select an observed dropdown value.",
    }
    operations = {key: labels[key] for key in targets}
    operations.update({key: value["label"] for key, value in controls.items()})
    operations.update(
        DONE="All requested work is complete, including applicable form Submit or search confirmation. No pending browser step remains. For read-and-report tasks, DONE hands the observed evidence to the answer writer; reporting itself needs no browser action.",
        BLOCKED="No supported operation can progress.",
    )
    if recovery:
        operations["DELEGATE"] = (
            "Use visual/browser recovery for an image or canvas that must be interpreted, a slider/drag/keyboard widget, "
            "a frame, shadow DOM, or an interaction that cannot be completed using the observed controls. "
            "Never guess unseen visual content. Prefer ordinary observed controls whenever they suffice."
        )
    rules = NEXT_ACTION
    if recovery:
        rules += "\nIf the task requires copying, reading or matching a pictured example, choose DELEGATE before manipulating its controls. A character named in the goal does not reveal the exact pictured pattern. Never guess pixels from a familiar symbol."
    questions = {"operation": {"type": "choice", "criteria": operations, "instructions": {"goal": goal, "rules": rules}}}
    for operation, candidates in targets.items():
        questions[operation.lower() + "_target"] = {
            "type": "choice",
            "criteria": {
                index: {
                    "element": f"[{index}] {a['label']}",
                    "current_value": a.get("current_value", a.get("value", "")),
                    **{
                        k: a[k]
                        for k in (
                            "role",
                            "checked",
                            "selected",
                            "expanded",
                            "current",
                            "context",
                            "position_in_parent",
                            "group",
                            "pagination",
                            "autocomplete",
                        )
                        if k in a
                    },
                }
                for index, a in candidates.items()
            },
            "instructions": {"goal": goal, "operation": operation, "rules": [NEXT_ACTION, TARGET]},
        }
    body = {
        "model": "jev-latest",
        "state": {
            "page": {k: state[k] for k in ("url", "title", "text")},
            "elements": elements,
            "visual_surfaces": state.get("visual_surfaces", []),
            "disabled_controls": state.get("disabled_controls", []),
            "recent_actions": [{k: h.get(k) for k in ("action", "kind", "text", "page_changed")} for h in history[-10:]],
        },
        "questions": questions,
    }
    started = time.perf_counter()
    result = post_json("jev", body)
    operation_answer = validate_choice(result["answers"].get("operation", {}), operations)
    operation = operation_answer["choice"]
    target = None
    target_answer = None
    probabilities = {}
    if operation in targets:
        # Unused target heads cannot cause an action. Validate the head selected by the operation.
        target_answer = validate_choice(result["answers"].get(operation.lower() + "_target", {}), targets[operation])
        target = target_answer["choice"]
        choice = targets[operation][target]["id"]
        probabilities = {a["id"]: target_answer["probabilities"][index] for index, a in targets[operation].items()}
    else:
        choice = controls[operation]["id"] if operation in controls else operation
        probabilities[choice] = operation_answer["probabilities"][operation]
    return {
        "choice": choice,
        "operation": operation,
        "target": target,
        "confidence": operation_answer["confidence"],
        "probabilities": probabilities,
        "operation_probabilities": operation_answer["probabilities"],
        "target_probabilities": target_answer["probabilities"] if target_answer else {},
        "target_confidence": target_answer["confidence"] if target_answer else None,
        "raw_answers": result["answers"],
        "model": result["model"],
        "usage": result.get("usage", {}),
        "latency_ms": round((time.perf_counter() - started) * 1000),
        "request": body,
    }


def _writer_evidence(value):
    # Ancestor labels/contexts can include the same standalone countdown as page text.
    # Exclude it from both the request and its freshness comparison; retain all other numbers.
    if isinstance(value, str):
        return re.sub(r"(?im)^\s*\d+(?:\.\d+)?\s*/\s*\d+(?:\.\d+)?\s*(?:sec|seconds?)\s*$", "", value)
    if isinstance(value, list):
        return [_writer_evidence(v) for v in value]
    if isinstance(value, dict):
        return {k: _writer_evidence(v) for k, v in value.items()}
    return value


def field_context(goal, action, page, history):
    evidence = {
        "field": {
            k: action.get(k) for k in ("node", "label", "role", "value", "autocomplete", "context", "position_in_parent", "group")
        },
        "page": {"title": page["title"], "text": page.get("writer_text", page["text"])[:6000]},
        "text_blocks": page.get("text_blocks", []),
        "fields": [
            {k: a.get(k) for k in ("node", "label", "role", "value", "context")} for a in page["actions"] if a["kind"] == "fill"
        ],
    }
    return {
        "goal": goal,
        **_writer_evidence(evidence),
        "recent_actions": [{k: h.get(k) for k in ("action", "text")} for h in history[-6:]],
    }


def review_completion(state, goal, history):
    """Audit a DONE claim with concrete pending actions, using Jev rather than a planner."""
    actions = {a["id"]: a for a in eligible_actions(state, goal) if a["kind"] != "wait"}
    criteria = {
        key: {
            "operation": a["kind"],
            **{
                k: a[k]
                for k in (
                    "label",
                    "role",
                    "value",
                    "current_value",
                    "current",
                    "checked",
                    "selected",
                    "expanded",
                    "context",
                    "pagination",
                )
                if k in a
            },
        }
        for key, a in actions.items()
    }
    criteria["DONE"] = "The requested task is complete; no authorized confirmation or navigation remains."
    criteria["BLOCKED"] = "The goal is incomplete but none of these actions can complete it."
    body = {
        "model": "jev-latest",
        "state": {
            "goal": goal,
            "page": {k: state[k] for k in ("title", "text", "url")},
            "recent_actions": [{k: h.get(k) for k in ("action", "kind", "text", "page_changed")} for h in history[-10:]],
        },
        "questions": {
            "remaining_action": {
                "type": "choice",
                "criteria": criteria,
                "instructions": "Audit task completion. Choose the next necessary authorized action, or DONE. "
                "A filled form with an unclicked Submit is usually still pending. Choose its Submit to finish the form "
                "unless the user requested no submission or a draft. Never extend authorization to purchases or messages. "
                "A request to read/search can finish with visible results. Do not act on unrelated controls. " + NEXT_ACTION,
            }
        },
    }
    started = time.perf_counter()
    result = post_json("jev", body)
    answer = validate_choice(result["answers"].get("remaining_action", {}), criteria)
    selected = answer["choice"]
    action = actions.get(selected)
    operation = {"fill": "TYPE_TEXT", "click": "CLICK", "select": "SELECT", "scroll": "SCROLL"}.get(
        action["kind"] if action else "", selected
    )
    return {
        **answer,
        "operation": operation,
        "target": action.get("node") if action else None,
        "latency_ms": round((time.perf_counter() - started) * 1000),
        "usage": result.get("usage", {}),
        "model": result["model"],
        "request": body,
        "completion_audit": True,
    }


def field_text(context):
    started = time.perf_counter()
    result = post_json(
        "field",
        {
            "messages": [{"role": "system", "content": TEXT_VALUE}, {"role": "user", "content": json.dumps(context)}],
            "schema": {
                "type": "object",
                "properties": {"text": {"type": ["string", "null"]}},
                "required": ["text"],
                "additionalProperties": False,
            },
        },
    )
    try:
        output = json.loads(result["content"])
        value = output["text"]
        if output == {"text": None}:
            raise FieldValueMissing("The field needs information from the user")
        if set(output) != {"text"} or not isinstance(value, str) or not value.strip() or len(value) > 2000:
            raise ValueError()
    except (ValueError, KeyError, TypeError):
        raise ValueError("Text helper returned no valid field value; nothing typed.") from None
    return value, {
        "model": result.get("model", "god"),
        "usage": result.get("usage", {}),
        "latency_ms": round((time.perf_counter() - started) * 1000),
    }
