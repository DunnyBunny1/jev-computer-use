"""General task entrypoint: fast Jev browser work and optional planning/native modes."""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
from contextlib import ExitStack
from pathlib import Path

from typesafe_sdk import TypeSafeClient

from .browser import act
from .browser.cdp import Chrome, Session, find_chrome
from .browser.decide import base_state
from .browser.orchestrator import run_task
from .browser.perceive import perceive
from .browser.report import RunFolder
from .config import load_dotenv
from .writer import make_writer
from .writer_fallback import from_env


def credentials():
    # Explicit process settings win, then an explicit/user config file, then
    # checkout-local settings. Installed wheels need no writable site-packages.
    configured = os.environ.get("COMPUTER_USE_ENV_FILE")
    config = Path(configured).expanduser() if configured else Path.home() / ".config" / "jev-computer-use" / ".env"
    if configured and not config.is_file():
        raise FileNotFoundError(f"COMPUTER_USE_ENV_FILE does not exist: {config}")
    load_dotenv(config)
    load_dotenv(Path(__file__).resolve().parents[1] / ".env")
    # Load the one TypeSafe credential from the user's existing key file, never
    # arbitrary shell content or every unrelated credential in that file.
    path = Path.home() / ".env"
    if path.is_file():
        for line in path.read_text().splitlines():
            key, _, value = line.partition("=")
            if key.strip() == "TYPESAFE_API_KEY":
                os.environ.setdefault("TYPESAFE_API_KEY", value.strip().strip("\"'"))
    os.environ.setdefault("CLICKER_WRITER_PROVIDERS", "openai,anthropic,fireworks,openrouter")
    os.environ.setdefault("CLICKER_PLANNER_PROVIDERS", "openai,openrouter,anthropic,fireworks")


def doctor():
    report = {
        "chrome": find_chrome(),
        "providers": {
            name: bool(os.environ.get(name + "_API_KEY"))
            for name in ("TYPESAFE", "OPENAI", "ANTHROPIC", "FIREWORKS", "OPENROUTER")
        },
    }
    try:
        from ApplicationServices import AXIsProcessTrusted
        from Quartz import CGPreflightScreenCaptureAccess

        report["desktop"] = {
            "accessibility": bool(AXIsProcessTrusted()),
            "screen_recording": bool(CGPreflightScreenCaptureAccess()),
        }
    except ImportError:
        report["desktop"] = {"available": False}
    print(json.dumps(report, indent=2))
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description="Browser Use with fast Jev decisions, visual recovery and local evidence")
    sub = ap.add_subparsers(dest="command", required=True)
    sub.add_parser("prepare", help="Cache locked Browser Use dependencies without opening a browser")
    sub.add_parser("doctor", help="Read capabilities and credential presence, never secret values")
    native = sub.add_parser("desktop", help="Bounded native task in one explicitly selected foreground app")
    native.add_argument("--app", required=True)
    native.add_argument("--goal", required=True)
    native.add_argument("--steps", type=int, default=12)
    native.add_argument("--handoffs", type=int, default=2)
    native.add_argument("--dry-run", action="store_true")
    native.add_argument("--out", type=Path, default=Path.home() / ".local/share/jev-computer-use/runs/native")
    for name in ("browser", "inspect"):
        p = sub.add_parser(name)
        p.add_argument("--url")
        p.add_argument("--attach-port", type=int, help="Attach to an explicitly selected local CDP browser")
        p.add_argument(
            "--profile", type=Path, help="Dedicated reusable automation profile; never use your normal browser profile"
        )
        p.add_argument("--headed", action="store_true")
        p.add_argument("--engine", choices=["hybrid", "browser-use", "ultrafast", "planned"], default="hybrid")
        p.add_argument("--out", type=Path, default=Path.home() / ".local/share/jev-computer-use/runs/tasks")
        p.add_argument("--goal", default="Inspect the current page")
        p.add_argument("--steps", type=int, default=60)
        p.add_argument("--seconds", type=float, default=180)
        p.add_argument("--rounds", type=int, default=24)
        p.add_argument("--no-vision", action="store_true")
        p.add_argument("--always-plan", action="store_true", help="Disable the Jev fast path")
        p.add_argument("--resume", type=Path, help="A prior task.json: reuse its goal and notes, then inspect fresh state")
    args = ap.parse_args(argv)
    credentials()
    if args.command == "prepare":
        from .browser.browser_use_engine import prepare_runtime

        prepare_runtime()
        return 0
    if args.command == "doctor":
        return doctor()
    if args.command == "desktop":
        from .actions import Context
        from .config import browser, email
        from .platform_adapter import desktop
        from .runner import RunConfig, run

        if not desktop.accessibility_trusted():
            ap.error("Enable the host app in macOS Privacy & Security > Accessibility")
        if args.steps <= 0 or args.handoffs < 0:
            ap.error("Steps must be positive and handoffs nonnegative")
        folder = RunFolder.create(args.out)
        planner = from_env(planner=True)
        cfg = RunConfig(
            goal=args.goal, out=folder.root, act=not args.dry_run, steps=args.steps, handoffs=args.handoffs, require_app=args.app
        )
        result = run(cfg, lambda client, history: Context(args.goal, browser(), email(), client, planner, history))
        print(
            json.dumps(
                {"folder": str(folder.root), "outcome": result.outcome, "answer": result.answer.text if result.answer else ""},
                indent=2,
            )
        )
        return 0 if result.answer and result.answer.achieved else 2
    notes = ""
    if args.resume:
        saved = json.loads(args.resume.read_text())
        args.goal, notes = saved["goal"], saved.get("notes", "")
        if not args.url and not args.attach_port:
            args.url = saved.get("url_after")
    if not args.url and not args.attach_port:
        ap.error("Provide --url or an explicitly selected --attach-port")
    if args.engine in {"browser-use", "hybrid"} and args.no_vision:
        ap.error("The Browser Use engine requires vision for recovery; use --engine ultrafast for text-only operation")
    folder = RunFolder.create(args.out)
    with ExitStack() as stack:
        if args.attach_port:
            browser = Chrome(port=args.attach_port)
            # Clean only the unused temporary profile created by the wrapper;
            # it did not launch or own the attached browser process.
            stack.callback(browser.close)
            # No start/close: the explicitly selected browser belongs to its owner.
        else:
            browser = stack.enter_context(Chrome(headed=args.headed, profile=str(args.profile) if args.profile else None))
        session = stack.enter_context(browser.attach())
        if args.engine in {"ultrafast", "browser-use", "hybrid"}:
            session.call(
                "Emulation.setDeviceMetricsOverride",
                {"width": 1120, "height": 780, "deviceScaleFactor": 1, "mobile": False},
            )
        if args.url:
            act.navigate(session, args.url)
            act.wait_for_load(session)
        if args.command == "inspect":
            result = base_state(args.goal, perceive(session), [], url_catalog=None)
            (folder.root / "observation.json").write_text(json.dumps(result, indent=2))
        elif args.engine in {"browser-use", "hybrid"}:
            from .browser.browser_use_engine import run_browser_use
            from .browser.hybrid import run_hybrid

            runner = run_hybrid if args.engine == "hybrid" and not args.always_plan else run_browser_use
            result = runner(
                session,
                args.goal,
                output=folder.root,
                max_steps=args.steps,
                max_seconds=args.seconds,
                **({} if runner is run_hybrid else {"jev": not args.always_plan}),
            )
            target = result.get("target_id")
            if target and target != session.ws_url.rsplit("/", 1)[-1]:
                if not re.fullmatch(r"[a-fA-F0-9]+", target):
                    raise ValueError("Invalid browser target in worker reply")
                session = stack.enter_context(Session(session.ws_url.rsplit("/", 1)[0] + "/" + target))
        elif args.engine == "ultrafast" and not args.always_plan:
            from .browser.ultrafast import run_ultrafast

            result = run_ultrafast(session, args.goal, output=folder.root, max_steps=args.steps, max_seconds=args.seconds)
        else:
            client = stack.enter_context(TypeSafeClient())
            result = run_task(
                session,
                client,
                args.goal,
                writer=make_writer(),
                planner=from_env(planner=True),
                output=folder.root,
                max_steps=args.steps,
                max_rounds=args.rounds,
                max_seconds=args.seconds,
                notes=notes,
                vision=not args.no_vision,
                fast_start=not args.always_plan,
            )
        shot = session.call("Page.captureScreenshot", {"format": "png"})
        (folder.root / "final.png").write_bytes(base64.b64decode(shot["data"]))
        # Use redacted perception rather than dumping all document text, which
        # could include unsent drafts or concealed content from unrelated panels.
        final = base_state(args.goal, perceive(session), [], url_catalog=None)
        (folder.root / "final-page.json").write_text(json.dumps(final, indent=2))
    print(
        json.dumps(
            {"folder": str(folder.root), "outcome": result.get("outcome", "inspected"), "answer": result.get("answer", "")},
            indent=2,
        )
    )
    return 0 if result.get("outcome", "complete") in {"complete", "done_unverified"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
