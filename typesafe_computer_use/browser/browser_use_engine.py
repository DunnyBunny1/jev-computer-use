"""Run the pinned full Browser Use engine in an isolated, cached uv environment."""

from __future__ import annotations

import json
import math
import os
import queue
import shutil
import signal
import subprocess
import threading
import time
from contextlib import suppress
from pathlib import Path
from urllib.parse import urlsplit


def prepare_runtime():
    """Install the locked upstream SDK environment without opening a browser."""
    uv = shutil.which("uv")
    if not uv:
        raise ValueError("Browser Use requires uv; install uv and retry")
    subprocess.run(
        [uv, "run", "--frozen", "--script", str(Path(__file__).with_name("browser_use_worker.py")), "--check"], check=True
    )


class Worker:
    def __init__(self, config, output, timeout):
        uv = shutil.which("uv")
        if not uv:
            raise ValueError("Browser Use requires uv; install uv and retry")
        worker = Path(__file__).with_name("browser_use_worker.py")
        self.log = (output / "browser-use.log").open("w")
        try:
            self.process = subprocess.Popen(
                [uv, "run", "--frozen", "--script", str(worker)],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=self.log,
                text=True,
                bufsize=1,
                start_new_session=os.name == "posix",
                env={**os.environ, "ANONYMIZED_TELEMETRY": "false", "BROWSER_USE_CLOUD_SYNC": "false"},
            )
        except Exception:
            self.log.close()
            raise
        self.messages = queue.Queue()

        def read():
            try:
                for line in self.process.stdout:
                    try:
                        message = json.loads(line)
                        if isinstance(message, dict):
                            self.messages.put(message)
                    except ValueError:
                        continue
            finally:
                self.messages.put({"error": "WorkerExited"})

        threading.Thread(target=read, daemon=True).start()
        try:
            self.send(config)
            if not self.receive(timeout).get("ready"):
                raise RuntimeError("Browser Use worker did not initialize")
        except Exception:
            self.close()
            raise

    def send(self, message):
        self.process.stdin.write(json.dumps(message) + "\n")
        self.process.stdin.flush()

    def receive(self, timeout):
        try:
            message = self.messages.get(timeout=max(0.01, timeout))
        except queue.Empty:
            raise TimeoutError("Browser Use step timed out") from None
        if message.get("error") == "TimeoutError":
            raise TimeoutError("Browser Use step timed out")
        if message.get("error"):
            raise RuntimeError("Browser Use worker failed: " + str(message["error"]))
        return message

    def close(self):
        if self.process.poll() is None:
            try:
                self.send({"command": "stop"})
                self.process.wait(timeout=3)
            except (OSError, subprocess.TimeoutExpired):
                if os.name == "posix":
                    with suppress(ProcessLookupError):
                        os.killpg(self.process.pid, signal.SIGTERM)
                else:
                    self.process.terminate()
                try:
                    self.process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    if os.name == "posix":
                        with suppress(ProcessLookupError):
                            os.killpg(self.process.pid, signal.SIGKILL)
                    else:
                        self.process.kill()
                    self.process.wait()
        for pipe in (self.process.stdin, self.process.stdout):
            if pipe:
                pipe.close()
        self.log.close()


def run_browser_use(session, goal, *, output, max_steps=60, max_seconds=180, stop_when=None, jev=True):
    if max_steps <= 0 or max_seconds <= 0 or not math.isfinite(max_seconds):
        raise ValueError("Action and time budgets must be positive")
    url = urlsplit(session.ws_url)
    if url.scheme != "ws" or url.hostname != "127.0.0.1" or not url.port:
        raise ValueError("Browser Use only attaches to the explicitly selected loopback browser")
    viewport = session.evaluate("({width:innerWidth,height:innerHeight})")
    config = {
        "cdp_url": f"http://127.0.0.1:{url.port}",
        "target_id": url.path.rsplit("/", 1)[-1],
        "goal": goal,
        "output": str(output),
        "viewport": viewport,
        "max_steps": max_steps,
        "jev": jev,
    }
    started = time.perf_counter()
    steps = 0
    outcome = "blocked"
    answer = ""
    failure = None
    last_url = session.evaluate("location.href")
    target_id = config["target_id"]
    worker = None
    try:
        worker = Worker(config, output, max_seconds)
        while steps < max_steps:
            if stop_when is not None and stop_when():
                outcome = "environment_terminated"
                break
            left = max_seconds - (time.perf_counter() - started)
            if left <= 0:
                outcome = "time_budget"
                break
            worker.send({"command": "step", "timeout": left, "remaining_actions": max_steps - steps})
            result = worker.receive(left + 1)
            last_url = result.get("url", last_url)
            target_id = result.get("target_id", target_id)
            steps += max(1, len(result.get("actions", [])))
            print(f"{steps:>3} Browser Use {json.dumps(result.get('actions', []))[:200]}", flush=True)
            if result.get("done"):
                outcome = "done_unverified" if result.get("success") else "blocked"
                answer = result.get("answer") or ""
                break
        else:
            outcome = "step_budget"
    except (RuntimeError, ValueError, OSError, TimeoutError) as exc:
        outcome = "time_budget" if isinstance(exc, TimeoutError) else "engine_error"
        failure = type(exc).__name__
    finally:
        if worker:
            worker.close()
    result = {
        "engine": "browser-use",
        "version": "0.13.10",
        "jev": jev,
        "goal": goal,
        "outcome": outcome,
        "error_type": failure,
        "answer": answer,
        "steps": steps,
        "wall_ms": round((time.perf_counter() - started) * 1000, 1),
        "url_after": last_url,
        "target_id": target_id,
    }
    (output / "task.json").write_text(json.dumps(result, indent=2))
    return result
