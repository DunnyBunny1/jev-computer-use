# Jev Computer Use

A standalone prototype combining **[Jev Ultrafast](https://github.com/browser-use/jev-ultrafast)** for speed with **[Browser Use](https://github.com/browser-use/browser-use)** for difficult browser interactions.

The normal loop reads visible controls and lets Jev select an action. A small model writes field values. Ambiguity can use a short text clarification; missing capabilities and visual tasks use full Browser Use on the same browser session. Ordinary recovery returns to the fast loop. Visual work stays with the visual executor until the subtask is finished or it explicitly hands control back.

This avoids running a large vision model on every step. There is no advance planning pass. It is a prototype, not a claim of universal reliability or SOTA. [Measurements and limits](docs/reliability.md).

## Install

Requires Python 3.12+, [uv](https://docs.astral.sh/uv/), Chrome/Chromium, a TypeSafe/Jev key, and a configured text/vision provider. macOS is the tested platform.

```sh
git clone https://github.com/DunnyBunny1/jev-computer-use.git
cd jev-computer-use
uv sync --frozen
cp .env.example .env
chmod 600 .env
# Edit .env with TYPESAFE_API_KEY and provider keys.
uv run computer-use prepare
uv run python scripts/install_skill.py
uv run computer-use doctor
```

Use `--replace` on the installer to update an existing `computer-use` skill. Keep this checkout and its `.venv`: the installed skill records that runtime. Keys can alternatively live in `~/.config/jev-computer-use/.env`; never commit them.

Try in Codex:

> Use $computer-use to find a round-trip JFK to SFO flight, November 12–16, 2026, for one adult in economy. Apply nonstop only. Verify the dates and filter, report a fare and source link, and do not book.

Or use the CLI:

```sh
uv run computer-use browser --url 'https://www.google.com/travel/flights' \
  --goal 'Find round-trip JFK to SFO flights November 12–16, 2026, one adult, economy, nonstop only. Do not book.'
```

Browser work is headless by default; `--headed` opens an isolated visible Chrome window for a demo and closes it afterward. It does not use the everyday browser profile or stream into Codex. Limits default to 60 action attempts and 180 seconds; change them with `--steps` and `--seconds`. For login use a dedicated `--profile /path` and enter credentials yourself.

The default engine is `hybrid`. `--engine browser-use` selects the previous full Browser Use loop; `--engine ultrafast` selects the fast loop without visual recovery; `--always-plan` runs the full agent without Jev for comparisons. Native Mac control remains a separate, limited backend; it has no broad desktop benchmark score.

## Models and evidence

Fast text defaults to OpenRouter Mercury 2.5 when configured, with provider fallbacks. Browser Use recovery prefers Fireworks Kimi K3, with GLM 5.3 Flash for focused image reading; other configured providers are available. `.env.example` documents overrides. `prepare` caches the locked Browser Use runtime without opening a browser.

Each run saves `task.json`, `ultrafast-trace.json`, `recoveries.json`, `final-page.json` and `final.png`; full recovery also saves its history and model calls. `done_unverified` is the agent's completion claim. Inspect the final page and screenshot independently before relying on an answer. Raw benchmark evidence stays local.

Observed text goes to Jev/text providers; recovery also sends screenshots to its vision provider. Browser Use telemetry and cloud sync are disabled. Run artifacts can contain private page content. CAPTCHA, login and consequential actions may require the user. Page content does not authorize purchases or messages. Password entry is not automated.

## Development and credits

```sh
uv run ruff check .
uv run ruff format --check .
uv run pytest -q
```

Offline tests block browser connections, desktop input and external networking. Live headless checks run separately.

Derived from [Aaron Levin's TypeSafe Computer Use](https://github.com/awlevin/typesafe-computer-use), [Browser Use](https://github.com/browser-use/browser-use), and [Jev Ultrafast](https://github.com/browser-use/jev-ultrafast). Original MIT notices are retained in [LICENSE](LICENSE) and the vendor directory. The internal Python package name remains `typesafe_computer_use` for compatibility; install this prototype from this repository, not the upstream PyPI package.
