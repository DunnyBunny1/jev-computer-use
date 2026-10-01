"""Host integration for Browser Use's pinned Jev Ultrafast loop; no planner."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

from .._vendor.jev_ultrafast.agent import Agent


def configure_text_model():
    """Use explicit upstream settings, otherwise bind a key to its own provider."""
    if os.environ.get("TEXT_MODEL_API_KEY"):
        return
    providers = [
        ("OPENROUTER_API_KEY", "https://openrouter.ai/api/v1", "inception/mercury-2.5"),
        ("OPENAI_API_KEY", "https://api.openai.com/v1", "gpt-4.1-nano"),
        ("FIREWORKS_API_KEY", "https://api.fireworks.ai/inference/v1", "accounts/fireworks/models/deepseek-v4p1-flash"),
    ]
    for key, url, model in providers:
        if os.environ.get(key):
            os.environ["TEXT_MODEL_API_KEY"] = os.environ[key]
            os.environ["TEXT_MODEL_BASE_URL"] = url
            os.environ.setdefault("TEXT_MODEL", model)
            os.environ.setdefault("TEXT_MODEL_REASONING", "none")
            return


def run_ultrafast(session, goal: str, *, output: Path, max_steps=60, max_seconds=180, stop_when=None):
    if max_steps <= 0 or max_seconds <= 0:
        raise ValueError("Action and time budgets must be positive")
    configure_text_model()
    started = time.perf_counter()
    agent = Agent(session, goal, screenshots=False)
    outcome, error, error_message = "blocked", None, None
    try:
        while True:
            state = agent.state
            if stop_when is not None and stop_when():
                outcome = "environment_terminated"
                break
            if state["status"] in {"done", "blocked"}:
                outcome = "done_unverified" if state["status"] == "done" else "blocked"
                break
            if time.perf_counter() - started >= max_seconds:
                outcome = "time_budget"
                break
            if len(state["history"]) >= max_steps or len(state["decisions"]) >= max_steps * 2:
                outcome = "step_budget"
                break
            before = len(state["history"])
            agent.command("tick")
            if len(state["history"]) > before:
                step = state["history"][-1]
                print(
                    f"{step['step']:>3} {step['operation']:<12} {step['action'][:90]} ({step['latency_ms']} ms Jev)", flush=True
                )
            (output / "ultrafast-trace.json").write_text(json.dumps(agent.snapshot(), indent=2))
    except (RuntimeError, ValueError, KeyError) as exc:
        # Never replay a possibly interrupted mutation or print provider payloads.
        outcome, error = "engine_error", type(exc).__name__
        if str(exc).startswith(
            ("Model provider returned HTTP", "Model connection failed", "Model unavailable", "Invalid TypeSafe", "Text helper")
        ):
            error_message = str(exc)
    finally:
        state = agent.snapshot()
        (output / "ultrafast-trace.json").write_text(json.dumps(state, indent=2))
        result = {
            "engine": "browser-use/jev-ultrafast",
            "upstream_commit": "1231850a0bf1a0c0341fe408ef1668dbbfdfac46",
            "goal": goal,
            "outcome": outcome,
            "error_type": error,
            "error_message": error_message,
            "answer": "Review final-page.json and final.png to verify and answer the task.",
            "steps": len(state["history"]),
            "decisions": len(state["decisions"]),
            "text_calls": len(state["text_calls"]),
            "planner_calls": len(state.get("recovery_calls", [])),
            "wall_ms": round((time.perf_counter() - started) * 1000, 1),
            "decision_loop_ms": state["elapsed_ms"],
            "url_after": state["page"]["url"],
        }
        (output / "task.json").write_text(json.dumps(result, indent=2))
        agent.close()
    return result
