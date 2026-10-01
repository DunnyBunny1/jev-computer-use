# Writer endpoints

## Planned browser tasks

`computer-use browser` runs a screenshot-capable planner around bounded Jev
segments. The planner retains notes, reads new scenes, reasons over tables and
returns an answer; Jev chooses actions and targets. Straightforward tasks first take a bounded Jev fast path; `--always-plan` disables it. The planner can bind exact text to uniquely labeled fields; otherwise nano composes text.
GPT-5.4 mini is the default planner, with low reasoning. Dense visual grids (16+ checkboxes), scrollable text, nested scrollers without editable fields, multiple unnamed visual controls and stalled subtasks selectively use GPT-5.4 low reasoning when the configured endpoint is GPT-5.4 mini. Other configured models are preserved. The override is scoped to that planning request and restored afterward, including on error. Override its model with
`CLICKER_PLANNER_OPENAI_MODEL`; analogous ANTHROPIC, FIREWORKS and OPENROUTER
variables select each fallback model. `CLICKER_PLANNER_PROVIDERS` overrides
the writer's provider order. `CLICKER_PLANNER_REASONING` overrides OpenAI-compatible
planner effort. Planner OpenRouter defaults to `openai/gpt-5.4-mini`;
other planner providers use the writer defaults below. The original reflex loop
remains available through `typesafe_computer_use.browser.bench`. Native
`computer-use desktop --app APP --goal GOAL` uses the planner model for writing
and reviewing the screen, with Jev selecting actions and bounded LLM handoffs.

The installed planner provider order is OpenAI, OpenRouter, Anthropic, Fireworks, so an equivalent model is tried before a weaker fallback. Two repeated unchanged scenes request expert recovery; four unchanged rounds stop with a stalled outcome.

Default browser limits are 60 actions, 24 planner rounds and 180 seconds. The benchmark explicitly keeps 12 planner rounds for comparability; raising the CLI ceiling does not change those scores.

The planner retains overall notes and history; each Jev segment receives only its current subtask and starts with an empty local action history. This prevents earlier clicks or scrolls from making a new repeated instruction look already completed.

Task folders contain `task.json` with planner usage, plus `segment-*/run.json`
with Jev usage and writer events. Count both when estimating cost. Screenshots
are sent to the planner and retained locally. `--no-vision` disables this but
cannot solve tasks requiring visible input contents or visual reference matching.
Four providers accepting requests does not establish their account balances.

## Optional provider fallback

Set `CLICKER_WRITER_PROVIDERS=openai,anthropic,fireworks,openrouter` to try configured
providers in that order and keep the first working provider for the process. This
overrides the single-endpoint writer settings below. Missing keys are skipped.

| Provider | Key variable | Default model |
| --- | --- | --- |
| OpenAI | `OPENAI_API_KEY` | `gpt-4.1-nano` |
| Anthropic | `ANTHROPIC_API_KEY` | `claude-haiku-4-5` |
| Fireworks | `FIREWORKS_API_KEY` | `accounts/fireworks/models/deepseek-v4p1-flash` |
| OpenRouter | `OPENROUTER_API_KEY` | `openai/gpt-4.1-nano` |

Each key is bound to its provider's fixed official endpoint. Override a model with
`CLICKER_OPENAI_MODEL`, `CLICKER_ANTHROPIC_MODEL`, `CLICKER_FIREWORKS_MODEL`, or
`CLICKER_OPENROUTER_MODEL`. The nano models do not reason; Haiku thinking is off;
Fireworks requests reasoning `none`. Fireworks is a fallback, not a small model.

An API error or malformed structured response advances to the next provider, with
one SDK attempt per provider per request and a 20-second request timeout. Existing
OpenAI response-format negotiation may make additional bounded compatibility
requests. Authentication, quota and rate-limit errors disable that provider for
the process. All failing providers produce a sanitized error, not an infinite retry.
Successful JSON is not proof its contents are correct. Browser run folders record
provider/model, token usage, latency and failure class, never key values.

The browser loop permits up to two automatic writer subgoal hints on uncertain
decisions. Jev still picks all actions and targets. Hints are cleared after a
changed input. This assistance must be disclosed in benchmark reports.

## Single endpoint

The writer types text, proposes URLs, and reads the screen whenever the classifier stops. By
default it is Claude on `api.anthropic.com`. These variables change the model or send it to
another endpoint.

| variable | required | purpose |
|---|---|---|
| `CLICKER_WRITER_BASE_URL` | no | send the writer to another endpoint; unset means `api.anthropic.com` |
| `CLICKER_WRITER_API_KEY` | no | the key for `CLICKER_WRITER_BASE_URL`, if it checks one |
| `CLICKER_WRITER_API` | no | what that endpoint speaks: `anthropic` (the default) or `openai` |
| `CLICKER_WRITER_MODEL` | no | types text and proposes URLs; defaults to `claude-haiku-4-5` |
| `CLICKER_ANSWER_MODEL` | no | reads the screen whenever the classifier stops; defaults to `claude-sonnet-5` |
| `CLICKER_WRITER_VISION` | no | `false` for an answer model that reads text only; defaults to `true` |
| `CLICKER_WRITER_REASONING` | no | the reasoning effort the writer's calls ask an OpenAI-API model for, such as `none`; unset leaves it to the model |
| `CLICKER_ANSWER_REASONING` | no | the same for the answer model, such as `low` |

## Other models

Point `CLICKER_WRITER_BASE_URL` at any endpoint that speaks the Anthropic
Messages API or, with `CLICKER_WRITER_API=openai`, OpenAI's Chat Completions API: LM Studio,
Ollama, vLLM, a LiteLLM proxy, DeepSeek. Name the models it serves. The full request URL works as
well as the root; for the OpenAI API keep the `/v1`. Such an endpoint may ignore structured-output
parameters, so the schema is also spelled out in the prompt, and code fences or a sentence around
the JSON are tolerated. On the OpenAI API a `json_schema` response format is asked for first, then
`json_object`, then none, stepping down only when the endpoint refuses one. Thinking is turned off,
since a model that thinks by default spends the writer's small token budgets on it and returns no
text. The answer model reads a screenshot; for a model that reads text only, set
`CLICKER_WRITER_VISION=false` and it gets the screen's text alone. A reply that cannot be read
refuses the step it was for, and the run goes on.

Keys never cross over: `CLICKER_WRITER_API_KEY` goes only to `CLICKER_WRITER_BASE_URL`, and
`ANTHROPIC_API_KEY` and `OPENAI_API_KEY` never go there. On the Anthropic API it is sent in both
the `x-api-key` and `Authorization` headers, since proxies differ. Leave it empty for an endpoint
that checks no key.

## Examples

```
# LM Studio, either of its two APIs
CLICKER_WRITER_BASE_URL=http://localhost:1234
CLICKER_WRITER_MODEL=qwen3.8-flash-next
CLICKER_ANSWER_MODEL=qwen3.8-flash-next

# any OpenAI-compatible server
CLICKER_WRITER_API=openai
CLICKER_WRITER_BASE_URL=https://api.deepseek.com/v1
CLICKER_WRITER_API_KEY=sk-...
CLICKER_WRITER_MODEL=deepseek-v4.1-flash
CLICKER_ANSWER_MODEL=deepseek-v4.1-flash
CLICKER_WRITER_VISION=false
```
