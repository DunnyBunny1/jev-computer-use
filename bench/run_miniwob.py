"""Run frozen MiniWoB tasks with the upstream evaluator isolated from the agent.

Uses CDP for normal inputs instead of Selenium. Reports raw success with a
120-second LLM-friendly timeout, not a standard MiniWoB leaderboard score.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import subprocess
import threading
import time
from contextlib import contextmanager
from datetime import UTC, datetime
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from typesafe_sdk import TypeSafeClient

from typesafe_computer_use.browser import act
from typesafe_computer_use.browser.cdp import CDPError, Chrome
from typesafe_computer_use.browser.orchestrator import run_task
from typesafe_computer_use.browser.report import RunFolder
from typesafe_computer_use.browser.runner import run_goal
from typesafe_computer_use.browser.ultrafast import run_ultrafast
from typesafe_computer_use.computer import credentials
from typesafe_computer_use.writer import make_writer
from typesafe_computer_use.writer_fallback import from_env


@contextmanager
def benchmark_origin(checkout, enabled):
    if not enabled:
        yield None
        return

    class QuietHandler(SimpleHTTPRequestHandler):
        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), partial(QuietHandler, directory=str(checkout / "miniwob/html")))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()


def wait_for_episode_page(session, url, timeout=15):
    """Observe the destination document before starting the frozen episode."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            ready = session.evaluate(
                f"location.href==={json.dumps(url)} && document.readyState==='complete' && typeof core!=='undefined' && typeof Math.seedrandom==='function'"
            )
            if ready is True:
                return
        except CDPError as exc:
            if not any(s in str(exc).lower() for s in ("context was destroyed", "cannot find context")):
                raise
        time.sleep(0.03)
    raise TimeoutError("Benchmark destination did not become ready")


class EpisodeGuard:
    """A reloaded document cannot earn credit for the original seeded episode."""

    def __init__(self, session):
        self.session = session
        self.loader = session.call("Page.getFrameTree")["frameTree"]["frame"]["loaderId"]
        self.started = session.evaluate("core.ept0")
        self.episode = session.evaluate("WOB_EPISODE_ID")
        self.reset = False

    def ended(self):
        loader = self.session.call("Page.getFrameTree")["frameTree"]["frame"]["loaderId"]
        self.reset = self.reset or loader != self.loader
        if not self.reset:
            state = self.session.evaluate("({start:core.ept0,episode:WOB_EPISODE_ID,done:WOB_DONE_GLOBAL})")
            self.reset = state["start"] != self.started or state["episode"] > self.episode + 1
            return self.reset or state["done"] is True
        return True


def main():
    ap = argparse.ArgumentParser(__doc__)
    ap.add_argument("--checkout", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument(
        "--mode", choices=["reflex", "planned", "adaptive", "ultrafast", "browser-use", "browser-use-llm"], required=True
    )
    ap.add_argument(
        "--split",
        choices=[
            "development",
            "heldout",
            "validation",
            "broad",
            "unseen",
            "repair",
            "generalization",
            "release_validation",
            "final_validation",
            "shipping_validation",
            "stable_validation",
            "completion_validation",
            "stability_repeat",
            "fast_comparison",
            "fast_reliability",
            "fast_transfer",
            "fast_final_unseen",
            "fast_prospective",
            "fast_holdout",
            "browser_use_holdout",
            "browser_use_extra",
            "browser_use_acceptance",
            "browser_use_fast_acceptance",
        ],
        default="development",
    )
    ap.add_argument("--task", default=None)
    ap.add_argument("--rounds", type=int, default=12)
    args = ap.parse_args()
    root = Path(__file__).resolve().parents[1]
    manifest = json.loads((root / "bench/miniwob-tasks.json").read_text())
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=args.checkout, text=True).strip()
    if commit != manifest["upstream_commit"]:
        raise ValueError("Benchmark checkout does not match frozen manifest")
    credentials()
    writer = make_writer()
    planner = from_env(planner=True)
    split = manifest[args.split]
    tasks = [args.task] if args.task else split["tasks"]
    if any(task not in split["tasks"] for task in tasks):
        raise ValueError("Task is outside the chosen frozen split")
    batch = args.output / (datetime.now(UTC).strftime("%Y%m%d-%H%M%S") + "-" + args.mode + "-" + args.split)
    batch.mkdir(parents=True, exist_ok=False)
    source_hashes = {
        str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted((root / "typesafe_computer_use").rglob("*"))
        if p.suffix in {".py", ".js", ".lock"}
    }
    (batch / "manifest.json").write_text(
        json.dumps(
            {
                **manifest,
                "mode": args.mode,
                "source_hashes": source_hashes,
                "max_planner_rounds": args.rounds,
                "browser_use_model": os.environ.get("BROWSER_USE_MODEL"),
                "browser_use_text_model": os.environ.get("BROWSER_USE_TEXT_MODEL"),
                "browser_use_provider": os.environ.get("BROWSER_USE_PROVIDER"),
                "browser_use_flash": os.environ.get("BROWSER_USE_FLASH") == "1",
                "browser_use_reasoning": os.environ.get("BROWSER_USE_REASONING", "low"),
            },
            indent=2,
        )
    )
    print(f"Batch: {batch}", flush=True)
    results = []
    with TypeSafeClient() as client, benchmark_origin(args.checkout, args.mode.startswith("browser-use")) as origin:
        for task in tasks:
            for seed in split["seeds"]:
                folder = batch / f"{task}-{seed}"
                folder.mkdir()
                started = time.perf_counter()
                row = {"task": task, "seed": seed, "pass": False}
                try:
                    with Chrome() as chrome, chrome.attach() as session:
                        session.call(
                            "Emulation.setDeviceMetricsOverride",
                            {"width": 500, "height": 700, "deviceScaleFactor": 1, "mobile": False},
                        )
                        url = (
                            f"{origin}/miniwob/{task}.html"
                            if origin
                            else (args.checkout / "miniwob/html/miniwob" / (task + ".html")).as_uri()
                        )
                        act.navigate(session, url)
                        wait_for_episode_page(session, url)
                        session.evaluate(
                            f"Math.seedrandom({json.dumps(str(seed))}); core.EPISODE_MAX_TIME={manifest['episode_timeout_seconds'] * 1000}; core.startEpisodeReal();"
                        )
                        goal = str(session.evaluate("document.querySelector('#query').innerText"))
                        row["goal"] = goal

                        # Evaluator state never enters an agent prompt. Only termination
                        # is used to stop further actions after upstream scores a task.
                        guard = EpisodeGuard(session)
                        ended = guard.ended

                        if args.mode.startswith("browser-use"):
                            from typesafe_computer_use.browser.browser_use_engine import run_browser_use

                            result = run_browser_use(
                                session,
                                goal,
                                output=folder,
                                max_steps=manifest["max_steps"],
                                max_seconds=manifest["episode_timeout_seconds"],
                                stop_when=ended,
                                jev=args.mode == "browser-use",
                            )
                            row.update(outcome=result["outcome"], steps=result["steps"])
                        elif args.mode == "ultrafast":
                            result = run_ultrafast(
                                session,
                                goal,
                                output=folder,
                                max_steps=manifest["max_steps"],
                                max_seconds=manifest["episode_timeout_seconds"],
                                stop_when=ended,
                            )
                            row.update(outcome=result["outcome"], steps=result["steps"])
                        elif args.mode == "reflex":
                            result = run_goal(
                                session,
                                client,
                                goal,
                                max_steps=manifest["max_steps"],
                                writer=writer,
                                runfolder=RunFolder(folder),
                                stop_when=ended,
                                deadline=time.perf_counter() + manifest["episode_timeout_seconds"],
                            )
                            row.update(outcome=result.outcome, steps=len(result.steps))
                        else:
                            result = run_task(
                                session,
                                client,
                                goal,
                                writer=writer,
                                planner=planner,
                                output=folder,
                                max_steps=manifest["max_steps"],
                                max_rounds=args.rounds,
                                max_seconds=manifest["episode_timeout_seconds"],
                                stop_when=ended,
                                fast_start=args.mode == "adaptive",
                            )
                            row.update(outcome=result["outcome"], steps=result["steps"])
                        ended()
                        grade = (
                            session.evaluate(
                                "({done:WOB_DONE_GLOBAL,raw_reward:WOB_RAW_REWARD_GLOBAL,reward:WOB_REWARD_GLOBAL,reason:WOB_REWARD_REASON})"
                            )
                            if not guard.reset
                            else {"done": False, "raw_reward": 0, "reason": "Episode document was reset"}
                        )
                        row.update(grade, **{"pass": bool(grade["done"] and grade["raw_reward"] == 1)})
                        shot = session.call("Page.captureScreenshot", {"format": "png"})
                        (folder / "final.png").write_bytes(base64.b64decode(shot["data"]))
                except Exception as exc:
                    row["error"] = type(exc).__name__
                    row["error_detail"] = str(exc)[:2000]
                row["total_ms"] = round((time.perf_counter() - started) * 1000, 1)
                results.append(row)
                (folder / "grade.json").write_text(json.dumps(row, indent=2) + "\n")
                (batch / "results.json").write_text(json.dumps(results, indent=2) + "\n")
                print(json.dumps(row), flush=True)
    print(f"Passed {sum(r['pass'] for r in results)}/{len(results)}; results: {batch}", flush=True)


if __name__ == "__main__":
    main()
