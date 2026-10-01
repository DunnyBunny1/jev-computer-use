"""Install the portable Codex skill against this checkout's Python runtime."""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import shutil
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path


def install(destination: Path, *, replace: bool = False) -> Path:
    root = Path(__file__).resolve().parents[1]
    source = root / "skills" / "computer-use"
    if importlib.util.find_spec("typesafe_computer_use") is None:
        raise RuntimeError("Run: uv run --frozen python scripts/install_skill.py")
    destination = destination.expanduser().absolute()
    if destination.exists() and not replace:
        raise FileExistsError(f"Skill already exists: {destination}; use --replace to back it up and update it")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="jev-skill-") as temporary:
        stage = Path(temporary) / "computer-use"
        shutil.copytree(source, stage, ignore=shutil.ignore_patterns("__pycache__", ".runtime.json"))
        (stage / ".runtime.json").write_text(json.dumps({"python": sys.executable, "engine": str(root)}, indent=2) + "\n")
        if destination.exists():
            backup_root = destination.parent.parent / "skill-backups"
            backup_root.mkdir(parents=True, exist_ok=True)
            backup = backup_root / (destination.name + "-" + datetime.now(UTC).strftime("%Y%m%d-%H%M%S-%f"))
            shutil.move(str(destination), str(backup))
            print(f"Previous skill saved outside active skills: {backup}")
        shutil.move(str(stage), str(destination))
    return destination


def main():
    parser = argparse.ArgumentParser(__doc__)
    codex_home = Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex")))
    parser.add_argument("--destination", type=Path, default=codex_home / "skills" / "computer-use")
    parser.add_argument("--replace", action="store_true", help="Back up the existing skill before updating it")
    args = parser.parse_args()
    path = install(args.destination, replace=args.replace)
    print(f"Installed: {path}\nInvoke $computer-use with your task. Use a new conversation if discovery is cached.")


if __name__ == "__main__":
    main()
