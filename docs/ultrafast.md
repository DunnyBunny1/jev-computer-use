# Jev Ultrafast: architecture and measurements

This is the v0.2.0.post2 baseline. See [reliability improvements](reliability.md) for the current engine and new validation.

Version 0.2.0.post2 changes the default to [Browser Use's Jev Ultrafast](https://github.com/browser-use/jev-ultrafast), copied under MIT at commit `1231850a0bf1a0c0341fe408ef1668dbbfdfac46`. The original attribution and license are preserved in [`_vendor/jev_ultrafast`](../typesafe_computer_use/_vendor/jev_ultrafast/UPSTREAM.md).

The loop observes visible DOM controls, asks Jev for an operation and speculative operation-specific targets in one request, executes the matching operation, and repeats. A text model supplies text only when typing is needed. There is **no per-action LLM planner**. The host reviews the final screenshot and page evidence; the engine's `done_unverified` status is not a success grade.

Local adaptations connect the loop to an isolated Chrome session, add budgets and evidence files, preserve checked states on visible labels for hidden radio/checkbox controls, expose custom clickable controls, and avoid redundant focus clicks. Testing runs headless. Visible Chrome requires `--headed`; the skill reserves this for an explicitly requested demo after the workflow works.

## Flight example

The fixed task searches JFK–SFO, round trip November 12–16, 2026, one adult, economy, nonstop only, without booking. Two final headless runs reached verified results in **8.742 and 8.197 seconds**, each with **12 actions, 19 Jev decisions, two text calls and zero planning calls**. Mercury 2.5 through OpenRouter supplied typed text.

Independent checks verify airports, dates decoded from the final Google Flights URL, round trip, one adult, economy, selected nonstop filter, closed popup and a visible fare. Final screenshots were also reviewed. The displayed example was Delta, 7:00 AM departure, $417 round trip; this is a dated search result, not a guaranteed purchasable fare. The grader is [`bench/verify_flight.py`](../bench/verify_flight.py) and is never supplied to the agent.

The earlier planned-engine search took **149.103 seconds**, including **129.605 seconds in planner requests** and **6.607 seconds in Jev requests**. These task-loop timings exclude initial browser launch/navigation, host verification and the final user response. The new engine stops at visible results for host verification, whereas the old planner also produced an answer, so this is a practical before/after example rather than a controlled speedup claim.

Development attempts are retained locally; current releases publish prose summaries only. Early runs failed on date controls, text-provider errors and an unapplied nonstop filter. One run was interrupted when the user requested closing the visible browser. A matching nonstop itinerary without an applied filter was correctly counted as a failure.

## Matched MiniWoB++ comparison

Twelve fixed task families, seed 88008, from MiniWoB++ commit `33c3b4ddef8c6eb67c57a29663d844b1eda7e614`. Each case uses a fresh headless Chrome, a 500 × 700 viewport, 40-action and 120-second budgets. The planned engine also allows 12 planning rounds. Success requires the upstream terminal flag **and raw reward exactly 1**. Neither engine receives hidden evaluator answers. Timing includes browser startup, execution and final evidence, and includes failures.

| Engine | Success | Median case time | Total time | Slowest case |
|---|---:|---:|---:|---:|
| Existing planned engine | 12/12 | 8.99 s | 180.94 s | 40.73 s |
| Initial Ultrafast adaptation | 8/12 | 1.58 s | 27.78 s | 5.67 s |
| Final Ultrafast adaptation | 9/12 | 1.66 s | 164.25 s | 138.50 s |

Raw results are retained locally. These are development tasks, not a blind held-out evaluation. One seed and small sample do not establish a general success rate or statistically reliable speed ratio.

Final failures: `search-engine` repeated pagination; `form-sequence-2` claimed completion before submission; `scroll-text` exposed unsupported nested scrolling, stale text retries and a text-provider failure. The last case took **138.5 seconds**: an in-flight provider request can overrun the loop deadline. Thus the lower median does not imply consistently low latency or a large aggregate throughput gain.

The fast engine is suitable for straightforward forms, links and filters, with independent verification. It is currently less reliable on this matched set than the slower planned engine. Use `--engine planned` explicitly when its broader recovery is needed; the fast engine does not silently switch to a slow planner. Neither the copied upstream flight demo nor these results establish SOTA. The older 94/104 score in [benchmark.md](benchmark.md) belongs to the planned engine only.

## Reproduction and evidence limits

Run `uv run python bench/run_miniwob.py --help` for checkout and output options; choose `--split fast_comparison --mode ultrafast` or `--mode adaptive`. The frozen task list is in [`bench/miniwob-tasks.json`](../bench/miniwob-tasks.json). Run the offline unit suite with `uv run pytest -q`; the live headless control fixture is separate at `bench/check_ultrafast_controls.py`.

Local records include every comparison case and recorded flight attempt. Final source hashes include the JavaScript snapshot implementation. Private raw model traces and screenshots are kept locally rather than published, limiting independent decision-level auditing. There is no official MiniWoB++ submission, OSWorld score, or matched evaluation against Codex computer use.
