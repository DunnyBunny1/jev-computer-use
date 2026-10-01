"""Headless live acceptance of shadow DOM, cross-origin frames and new tabs.

Local functional fixtures, not part of the MiniWoB benchmark score. Receipts
are recorded server-side and never passed to the agent as answers.
"""

from __future__ import annotations

import argparse
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from typesafe_computer_use.browser import act
from typesafe_computer_use.browser.browser_use_engine import run_browser_use
from typesafe_computer_use.browser.cdp import Chrome
from typesafe_computer_use.computer import credentials

FORM = """<form><label>Name <input name="name"></label><button>Save</button></form><p id="receipt"></p>"""
SCRIPT = """<script>
const form=document.querySelector('form');
form.onsubmit=async event=>{event.preventDefault();
 const value=form.elements.name.value;
 await fetch('/receipt',{method:'POST',body:JSON.stringify({path:location.pathname,value})});
 document.querySelector('#receipt').textContent='Saved '+value;
};
</script>"""


def main():
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    credentials()
    receipts = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == "/shadow":
                page = (
                    """<h1>Shadow form</h1><div id="host"></div><script>
const root=document.querySelector('#host').attachShadow({mode:'open'});
root.innerHTML="""
                    + json.dumps(FORM)
                    + """;
root.querySelector('form').onsubmit=async event=>{event.preventDefault();
 const value=root.querySelector('input').value;
 await fetch('/receipt',{method:'POST',body:JSON.stringify({path:location.pathname,value})});
 root.querySelector('#receipt').textContent='Saved '+value;};</script>"""
                )
            elif self.path == "/frame":
                page = f'<h1>Embedded form</h1><iframe title="Profile panel" src="http://localhost:{self.server.server_port}/panel" style="width:700px;height:400px"></iframe>'
            elif self.path == "/tabs":
                page = '<h1>Workspace</h1><a href="/editor" target="_blank">Open editor</a>'
            else:
                page = "<h1>Profile editor</h1>" + FORM + SCRIPT
            data = (
                '<!doctype html><meta charset="utf-8"><style>body{font:20px sans-serif;padding:30px}input,button{font:inherit;margin:12px}</style>'
                + page
            ).encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_POST(self):
            receipts.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"ok")

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    cases = [
        ("shadow", "Enter Mira in the Name field in the shadow form and Save.", "/shadow", "Mira"),
        ("frame", "Inside the embedded Profile panel, enter Rowan in the Name field and Save.", "/panel", "Rowan"),
        ("tabs", "Open the editor in its new tab, enter Orchid in the Name field and Save.", "/editor", "Orchid"),
    ]
    results = []
    try:
        for name, goal, receipt_path, value in cases:
            folder = args.output / name
            folder.mkdir()
            receipts.clear()
            with Chrome() as chrome, chrome.attach() as session:
                act.navigate(session, f"http://127.0.0.1:{server.server_port}/{name}")
                act.wait_for_load(session)
                result = run_browser_use(
                    session, goal, output=folder, max_steps=30, max_seconds=120, stop_when=lambda: bool(receipts)
                )
                passed = receipts == [{"path": receipt_path, "value": value}]
                results.append(
                    {
                        "case": name,
                        "pass": passed,
                        "steps": result["steps"],
                        "wall_ms": result["wall_ms"],
                        "outcome": result["outcome"],
                    }
                )
                print(json.dumps(results[-1]), flush=True)
            (args.output / "results.json").write_text(json.dumps(results, indent=2))
    finally:
        server.shutdown()
        server.server_close()
    return 0 if all(r["pass"] for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
