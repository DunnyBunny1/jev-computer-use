"""Jev Ultrafast's normal loop, with lazy full Browser Use recovery on the same browser."""

from __future__ import annotations

import json
import math
import time
from contextlib import ExitStack
from urllib.parse import urlsplit

from .._vendor.jev_ultrafast import model
from .._vendor.jev_ultrafast.agent import Agent
from .._vendor.jev_ultrafast.browser import StalePage
from .browser_use_engine import Worker
from .browser_use_policy import permitted_navigation
from .cdp import Session
from .ultrafast import configure_text_model


def run_hybrid(session, goal, *, output, max_steps=60, max_seconds=180, stop_when=None):
    if max_steps <= 0 or max_seconds <= 0 or not math.isfinite(max_seconds):
        raise ValueError("Action and time budgets must be positive")
    address = urlsplit(session.ws_url)
    if address.scheme != "ws" or address.hostname != "127.0.0.1" or not address.port:
        raise ValueError("Recovery only attaches to the explicitly selected loopback browser")
    configure_text_model()
    started = time.perf_counter()
    deadline = started + max_seconds
    target_id = address.path.rsplit("/", 1)[-1]
    previous_deadline = model.DEADLINE
    model.DEADLINE = deadline
    worker = agent = None
    steps = failures = 0
    recoveries = []
    advised_pages = set()
    visual_recovery = False
    outcome, error, answer = "blocked", None, "Review final-page.json and final.png to verify and answer the task."
    last_url = None
    try:
        last_url = session.evaluate("location.href")
        with ExitStack() as owned:
            known_targets = {t["targetId"] for t in session.call("Target.getTargets")["targetInfos"]}
            agent = Agent(session, goal, screenshots=False, external_recovery=True)
            while steps < max_steps:
                left = deadline - time.perf_counter()
                if left <= 0:
                    outcome = "time_budget"
                    break
                if stop_when is not None and stop_when():
                    outcome = "environment_terminated"
                    break
                if not permitted_navigation(agent.state["page"]["url"]):
                    outcome = "blocked"
                    break
                state = agent.state
                reason = "visual-continuation" if visual_recovery else "blocked" if state["status"] == "blocked" else None
                try:
                    if reason is None:
                        agent.command("predict")
                        choice = state["decision"]
                        reason = choice.get("recover") or ("blocked" if choice["choice"] == "BLOCKED" else None)
                    if reason in {"uncertain", "repeated-actions"} and state["page"]["fingerprint"] not in advised_pages:
                        advised_pages.add(state["page"]["fingerprint"])
                        focus, helper = model.recovery_focus(state["page"], state["goal"], state["history"])
                        state.setdefault("recovery_calls", []).append({**helper, "focus": focus})
                        if focus:
                            choice = model.choose(
                                state["page"], state["goal"] + "\nNext-step guidance: " + focus, state["history"], recovery=True
                            )
                            state["decisions"].append({**choice, "recovery": True})
                            if (
                                choice["choice"] not in {"DONE", "BLOCKED", "DELEGATE"}
                                and (
                                    choice["target_confidence"]
                                    if choice.get("target_confidence") is not None
                                    else choice["confidence"]
                                )
                                >= 0.6
                            ):
                                state["decision"] = choice
                                reason = None
                    if reason is None:
                        # Prediction can include text-only completion verification.
                        agent.command("act", {"fingerprint": state["page"]["fingerprint"]})
                        steps += 1
                        failures = 0
                        if choice["operation"] == "CLICK":
                            tabs = session.call("Target.getTargets")["targetInfos"]
                            opened = [
                                t
                                for t in tabs
                                if t["type"] == "page" and t["targetId"] not in known_targets and t.get("openerId") == target_id
                            ]
                            known_targets.update(t["targetId"] for t in tabs)
                            if len(opened) == 1:
                                target_id = opened[0]["targetId"]
                                session = owned.enter_context(Session(session.ws_url.rsplit("/", 1)[0] + "/" + target_id))
                                agent.browser.session = session
                                state["page"] = agent.browser.observe(screenshot=False)
                        last_url = state["page"]["url"]
                        print(f"{steps:>3} Jev {state['status']} {choice['operation']}", flush=True)
                        if state["status"] == "done":
                            outcome = "done_unverified"
                            break
                        (output / "ultrafast-trace.json").write_text(json.dumps(agent.snapshot(), indent=2))
                        continue
                except StalePage:
                    # Discard a stale selection. Never retry its browser action blindly.
                    state.update(decision=None, status="ready", page=agent.browser.observe(screenshot=False))
                    steps += 1
                    continue
                except (RuntimeError, ValueError, KeyError) as exc:
                    failures += 1
                    reason = type(exc).__name__
                    # Malformed inference is safe to retry once: it has not executed.
                    if str(exc).startswith("Invalid TypeSafe") and failures == 1:
                        state.update(decision=None, status="ready", page=agent.browser.observe(screenshot=False))
                        steps += 1
                        continue
                left = deadline - time.perf_counter()
                if left <= 0:
                    outcome = "time_budget"
                    break
                context = {
                    "reason": reason,
                    "recent_actions": [
                        {k: h.get(k) for k in ("action", "text", "page_changed", "url")} for h in state["history"][-10:]
                    ],
                    "previous_recovery": recoveries[-1].get("memory", "") if recoveries else "",
                }
                if worker is None:
                    worker = Worker(
                        {
                            "cdp_url": f"http://127.0.0.1:{address.port}",
                            "target_id": target_id,
                            "goal": goal,
                            "output": str(output),
                            "viewport": session.evaluate("({width:innerWidth,height:innerHeight})"),
                            "max_steps": max_steps,
                            "jev": False,
                            "recovery_mode": True,
                        },
                        output,
                        left,
                    )
                left = deadline - time.perf_counter()
                if left <= 0:
                    outcome = "time_budget"
                    break
                worker.send(
                    {
                        "command": "step",
                        "timeout": left,
                        "remaining_actions": max_steps - steps,
                        "recovery_context": context,
                        "target_id": target_id,
                    }
                )
                result = worker.receive(left + 1)
                steps += max(1, len(result.get("actions", [])))
                recoveries.append({"reason": reason, **result})
                last_url = result.get("url", last_url)
                print(f"{steps:>3} Recovery {json.dumps(result.get('actions', []))[:180]}", flush=True)
                new_target = result.get("target_id", target_id)
                if new_target != target_id:
                    if (
                        not isinstance(new_target, str)
                        or not new_target
                        or any(c not in "0123456789abcdefABCDEF" for c in new_target)
                    ):
                        raise ValueError("Invalid browser target in recovery reply")
                    session = owned.enter_context(Session(session.ws_url.rsplit("/", 1)[0] + "/" + new_target))
                    target_id = new_target
                    agent.browser.session = session
                if result.get("done"):
                    outcome = "done_unverified" if result.get("success") else "blocked"
                    answer = result.get("answer") or answer
                    break
                actions = result.get("actions", [])
                if any("inspect_region" in action or "drag" in action for action in actions):
                    visual_recovery = True
                if any("resume_fast" in action for action in actions):
                    visual_recovery = False
                # Recovery reads and actions become context, never hardcoded selectors.
                # Keep the original task and only the latest recovery facts to avoid stale guidance.
                observations = [str(x) for x in result.get("observations", []) if x]
                # Private Browser Use indices must not become Ultrafast targets.
                guidance = "\n".join(observations)[-6000:]
                state["goal"] = goal + "\nRecovery observations (verify against the current page):\n" + guidance
                state["history"].append(
                    {
                        "action": "Browser Use recovery: " + guidance,
                        "kind": "recovery",
                        "text": None,
                        "page_changed": True,
                        "url": last_url,
                    }
                )
                agent.pending_text = None
                state.update(decision=None, status="ready", page=agent.browser.observe(screenshot=False))
                failures = 0
            else:
                outcome = "step_budget"
    except (RuntimeError, ValueError, OSError, TimeoutError) as exc:
        outcome = "time_budget" if isinstance(exc, TimeoutError) else "engine_error"
        error = type(exc).__name__
    finally:
        model.DEADLINE = previous_deadline
        if worker:
            worker.close()
        if agent:
            (output / "ultrafast-trace.json").write_text(json.dumps(agent.snapshot(), indent=2))
            agent.close()
        (output / "recoveries.json").write_text(json.dumps(recoveries, indent=2))
    result = {
        "engine": "hybrid",
        "goal": goal,
        "outcome": outcome,
        "error_type": error,
        "answer": answer,
        "steps": steps,
        "recovery_steps": len(recoveries),
        "wall_ms": round((time.perf_counter() - started) * 1000, 1),
        "url_after": last_url,
        "target_id": target_id,
    }
    (output / "task.json").write_text(json.dumps(result, indent=2))
    return result
