# Evaluation: October 1, 2026

This report measures the historical **planned engine**, available with `--engine planned`. The default changed in v0.2.0.post2; its separate results and limitations are in [Jev Ultrafast](ultrafast.md). The 90.4% below does not describe the new default.

## Result and scope

The final v9 engine passed **94 of 104 cases (90.4%)**: 52 MiniWoB++ task families on each of two fresh random seeds. Each run passed 47/52. Median end-to-end case time was **5.721 seconds**, p95 **31.872 seconds**, and estimated recorded inference cost **$1.323867** for all 104 cases (about 1.3 cents/case).

This is an **adapted subset of a vetted benchmark**, not a vetted result or an official leaderboard submission. These task families informed development; the final seeds were fresh, not the task families. No matched comparison against Codex's computer-use tool or another agent was run. No OSWorld score was measured. **This does not establish SOTA or a 90% success rate on arbitrary websites or desktop tasks.**

The exact measured Python engine is commit [`5acd74f70418e050812bec68941b79f0a8336e4a`](https://github.com/DunnyBunny1/typesafe-computer-use/commit/5acd74f70418e050812bec68941b79f0a8336e4a). Every engine file's SHA-256 matches the saved run manifests. The v0.2.0.post1 release adds portable configuration, installer, metadata and documentation; it does not change the action/planning algorithm. Packaging has separate offline and fresh-install validation, not a newly measured browser score.

## Protocol

- Upstream: [Farama MiniWoB++](https://github.com/Farama-Foundation/miniwob-plusplus), frozen commit `33c3b4ddef8c6eb67c57a29663d844b1eda7e614`.
- Task list and seeds: [`bench/miniwob-tasks.json`](../bench/miniwob-tasks.json), `completion_validation` (88006) and `stability_repeat` (88007).
- Fresh isolated Chrome per case, 500 × 700 viewport; page opened from the pinned local checkout. Normal inputs use Chrome DevTools Protocol rather than Selenium.
- Adaptive Jev fast path plus LLM planning, 40 decisions, 12 planning rounds and 120 seconds per case. The page's timeout is extended to 120 seconds. An in-flight API call may exceed a deadline.
- Goal comes from visible `#query` text. Agent observations include rendered DOM controls and screenshots, not hidden evaluator answers or reward state. The evaluator's terminal flag stops further inputs.
- **Success requires upstream terminal state AND raw reward exactly 1.** A model claiming completion does not pass; partial rewards count as failures. This is raw success, not the upstream time-discounted reward.
- Latency includes browser launch, inference, actions, evaluation and final screenshot. It is measured wall time on the author's Mac, not a controlled cross-agent speed comparison. Latency summarizes all cases, including failures.

Raw benchmark evidence is retained locally and excluded from current Git releases. Historical results are summarized here; historical tags retain files previously published. Current Browser Use results and limits are summarized in [browser reliability](reliability.md).

### Actual models and cost

Jev `jev-1.13.0` selected actions. Recorded final-batch planner calls used `openai/gpt-5.4-mini` and selectively `openai/gpt-5.4` through OpenRouter; Fireworks `deepseek-v4p1-flash` handled fallback calls. Defaults try direct OpenAI first and use low reasoning; provider availability caused fallback in these runs. Default nano text writing was configured but is not the model recorded for those final fallback calls. Usage by actual model is retained in the local evaluation records.

Costs are token-based estimates using rates recorded during evaluation, not billing receipts. They exclude Codex's own work, native smoke tests, earlier unrecorded work and any failed request usage not returned by a provider. Recorded iteration inference totaled about **$18.04**. Provider/model availability, endpoint behavior and pricing can change.

## Failures retained

| Seed | Failed tasks |
|---|---|
| 88006 | click-color, number-checkboxes, find-greatest, click-shape, book-flight-nodelay |
| 88007 | click-color, count-shape, click-shape, social-media, book-flight-nodelay |

Weaknesses include tiny visual references, shape/color interpretation, some icon choices and budget exhaustion in the synthetic flight form. Both synthetic flight cases remained failures. The successful real Google Flights check below does not override them.

The earlier broad baseline was 63/80. A tuned run reached 79/80 on that broad set, but it is not the final generalization score. Initial testing on additional task families scored 23/36 before repairs. Later tests reused those families. The final 94/104 uses different seeds and a different task mix, so it is not a matched 63/80 → 94/104 comparison. All recorded batch totals, including regressions, are retained locally.

## Real tasks and desktop checks

| Check | Result | Time | Estimated inference |
|---|---|---:|---:|
| v9 Google Flights: JFK–SFO, November 12–16, 2026, 1 adult, economy, nonstop | Completed; dates, route, fare and filter checked separately against final page/URL; no booking | 106.5 s | $0.589 |
| v8 Python docs: locate Path.mkdir and explain parents/exist_ok | Completed; answer checked against official method documentation | 78.0 s | $0.121 |
| Native TextEdit: read a note / exact text replacement | Passed bounded smoke checks | 5.9 / 10.8 s | Not included |

These were manually graded spot checks by the development agent using saved evidence, not independent third-party evaluations. An earlier flight attempt that reached the right page but stalled its answer was graded a failure. The docs run also needed search recovery; it was not a fast direct lookup. Native coverage is limited; the Mac later locked and blocked further native testing. OSWorld was not run.

## Reproduce

Install the release and configure keys as in the [README](../README.md), then:

```sh
git clone https://github.com/Farama-Foundation/miniwob-plusplus.git /tmp/jev-miniwob
git -C /tmp/jev-miniwob checkout 33c3b4ddef8c6eb67c57a29663d844b1eda7e614
uv run --frozen python bench/run_miniwob.py --checkout /tmp/jev-miniwob --output ./results --mode adaptive --split completion_validation
uv run --frozen python bench/run_miniwob.py --checkout /tmp/jev-miniwob --output ./results --mode adaptive --split stability_repeat
```

These commands launch headless Chrome and spend API credits. Use `--task click-button` for one bounded smoke case. For the exact pre-packaging source, check out commit `5acd74f` in a separate worktree; its bootstrap expects the original checkout `.env` and an existing `~/.env`. The release removes that portability assumption. Models remain hosted and nondeterministic, so frozen code/seeds do not guarantee identical scores.

Before changing the engine, freeze the next task list, random seeds, budget and success criteria. Keep the failed cases. For stronger general-purpose evidence, evaluate new task families and a substantially larger frozen set, then run a matched baseline and OSWorld in an isolated VM. Do not compare differently configured leaderboard percentages as if they were the same experiment.
