# Jev Computer Use

An installable Codex skill built on **[Browser Use](https://github.com/browser-use/browser-use)**, with Jev for fast decisions and a vision model for difficult steps. Browser Use handles the page, controls, screenshots, history, tabs, embedded frames and shadow DOM. A small text model fills fields; the full visual agent takes over when needed.

Standalone prototype by Donovan Murray, derived from [Aaron Levin's TypeSafe Computer Use](https://github.com/awlevin/typesafe-computer-use), with upstream MIT notices retained. The browser foundation is now the full Browser Use library, pinned to **0.13.10**, rather than the narrow Jev Ultrafast fork. The older engines remain available explicitly. No new model is trained here.

[Short results and limitations](docs/reliability.md). These local browser tests are not a SOTA or general desktop claim. Raw evaluation traces remain local; only the protocol and brief summaries are published.

## Install

Requirements: Python 3.12+, [uv](https://docs.astral.sh/uv/getting-started/installation/), Chrome or Chromium, a [TypeSafe/Jev](https://typesafe.ai/) key, and a Fireworks, OpenRouter, OpenAI or Anthropic key. macOS is the locally tested platform. Browser Use's locked dependencies run in a separate cached environment so they do not conflict with the legacy native engine.

```sh
git clone https://github.com/DunnyBunny1/jev-computer-use.git
cd jev-computer-use
uv sync --frozen
uv run --frozen computer-use prepare
uv run --frozen python scripts/install_skill.py
cp .env.example .env
chmod 600 .env
# Edit .env: set TYPESAFE_API_KEY and at least one text/vision provider key.
uv run --frozen computer-use doctor
```

Keep the checkout and `.venv` in place: the skill records that runtime. Installation defaults to `~/.codex/skills/computer-use`, honors `CODEX_HOME`, and accepts `--destination PATH`. Use `--replace` to update an existing skill; the installer backs up its previous files outside active skills. Start a new Codex conversation if discovery is cached. No separate TypeSafe skill is needed.

Try:

> Use $computer-use to open Python's official documentation, find pathlib.Path.mkdir, and explain parents=True and exist_ok=True. Include the source URL.

Or:

> Use $computer-use to find a round-trip JFK to SFO flight, November 12–16, 2026, for one adult in economy. Apply nonstop only. Report one matching fare, airline, departure time and source link. Verify the dates and filter; do not book.

Websites and fares change; these are example tasks, not guaranteed outcomes. [Skill instructions](skills/computer-use/SKILL.md).

## Standalone CLI

```sh
uv tool install 'git+https://github.com/DunnyBunny1/jev-computer-use.git'
computer-use prepare
computer-use browser --engine browser-use --url 'https://docs.python.org/3/library/pathlib.html' \
  --goal 'Find Path.mkdir and explain parents=True and exist_ok=True with the source URL.'
```

For an installed wheel or tool, put keys in `~/.config/jev-computer-use/.env`, export them, or set `COMPUTER_USE_ENV_FILE` to a private file. Environment variables take precedence, followed by that config file and checkout `.env`. Legacy `~/.env` contributes only `TYPESAFE_API_KEY`.

The Browser Use engine automatically tries configured providers in order: Fireworks (Kimi K3 vision and DeepSeek V4.1 Flash text), OpenRouter, OpenAI (GPT-5.4 vision and GPT-4.1 mini text), then Anthropic (Sonnet 4.6 and Haiku 4.5). It advances only on authentication, quota or billing errors during inference; it never repeats a browser action as part of failover. Set `BROWSER_USE_PROVIDER` to pin one provider, then optionally override `BROWSER_USE_MODEL` and `BROWSER_USE_TEXT_MODEL`. In automatic mode use provider-specific names such as `BROWSER_USE_FIREWORKS_MODEL`. Fireworks uses GLM-5.3 Flash for focused image transcription. Visual recovery costs more and takes longer than the simple Jev path. Jev handles simple actions without a vision-model call. `--always-plan` disables Jev for comparison with the full agent.

Limits default to 60 action attempts and 180 seconds (`--steps`, `--seconds`). `prepare` downloads the pinned runtime without opening a browser, avoiding dependency setup during the first task. `--resume task.json` restores the goal and URL, not a previous browser session.

Each run produces `task.json`, `browser-use-history.json`, `model-calls.json`, `models.json`, `final-page.json` and `final.png`. `done_unverified` is a completion claim; inspect the final evidence before relying on it.

## Architecture

```text
Browser Use observation → Jev operation and target → Browser Use execution
                          ↓ text field
                          small text model
                          ↓ uncertainty, unsupported action or vision needed
                          full Browser Use vision agent for the remaining task
```

Browser Use supplies the observation and execution implementation. Small extensions expose its drag API and magnified screenshot regions. The adapter keeps upstream history and uses upstream action validation. It excludes arbitrary JavaScript and filesystem actions. Observed page content does not authorize purchases, messages or account changes; this is not a complete prompt-injection security boundary.

`--engine ultrafast` retains the previous lightweight Browser Use Jev Ultrafast loop. `--engine planned` retains the older planner. Their historical measurements are documented separately and must not be attributed to the new engine.

## Scope and privacy

Browser work is headless by default. `--headed` opens a visible demonstration. This uses isolated Chrome, not Codex's in-app browser, and does not stream its screen into chat. For login, use a dedicated `--profile /path` and sign in yourself. Never select your everyday browser profile. `--attach-port` attaches only to an explicitly selected dedicated local CDP browser.

Jev and the text model receive observed page text; visual recovery also sends screenshots to the vision provider. Browser Use telemetry and cloud sync are disabled. Artifacts remain on disk and can contain private page content. Do not publish `.env`, profiles or run folders. CAPTCHA, login and consequential actions may require the user.

Native Mac control remains a separate, limited backend: `computer-use desktop --app TextEdit --goal 'Read the front document.'`. The named app must already be foreground and the host needs Accessibility and Screen Recording permissions. It moves the real pointer and keyboard. Native acceptance is limited to TextEdit smoke tests; no OSWorld score is established. Inherited Windows support has not been accepted in this prototype.

## Packaging and development

The Python package exposes `computer-use`; `skills/computer-use/` contains the portable skill. The optional `.codex-plugin/plugin.json` exposes the same skill but does not install Python dependencies: install the CLI first. Avoid installing duplicate skill copies. Install this prototype from GitHub; the inherited PyPI package name belongs to the upstream project.

```sh
uv sync --frozen
uv run ruff check .
uv run ruff format --check .
uv run pytest -q
uv build
```

Offline tests refuse desktop input, browser connections and external networking. Live headless checks run separately. [Benchmark protocol](docs/benchmark.md), [legacy fast-engine attribution](docs/ultrafast.md), [upstream OSWorld integration](docs/osworld.md).

Original engine: [Aaron Levin / TypeSafe](https://github.com/awlevin/typesafe-computer-use). Browser engine: [Browser Use](https://github.com/browser-use/browser-use); legacy loop: [Jev Ultrafast](https://github.com/browser-use/jev-ultrafast), with its MIT notice in the vendor directory. MiniWoB++: [Farama Foundation](https://github.com/Farama-Foundation/miniwob-plusplus), downloaded separately. [MIT license](LICENSE).
