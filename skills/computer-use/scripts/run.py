"""Run the configured engine without assuming an author-specific filesystem path."""

from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path


def command(arguments: list[str]) -> list[str]:
    runtime = Path(__file__).resolve().parents[1] / ".runtime.json"
    if runtime.is_file():
        python = Path(json.loads(runtime.read_text())["python"])
        if not python.is_file():
            raise SystemExit("The configured Python moved. Rerun scripts/install_skill.py --replace in your checkout.")
        return [str(python), "-m", "typesafe_computer_use.computer", *arguments]
    executable = shutil.which("computer-use")
    if executable:
        return [executable, *arguments]
    raise SystemExit(
        "Engine missing. Install the Python CLI and rerun: uv tool install "
        "git+https://github.com/DunnyBunny1/jev-computer-use.git@v0.2.0.post3"
    )


if __name__ == "__main__":
    invocation = command(sys.argv[1:])
    os.execv(invocation[0], invocation)
