# Browser Use Jev Ultrafast

Source: https://github.com/browser-use/jev-ultrafast
Pinned commit: 1231850a0bf1a0c0341fe408ef1668dbbfdfac46
License: MIT, reproduced in LICENSE.

Copied agent.py, browser.py, model.py, questions.py and snapshot.js. Local changes:
- Browser accepts the host's isolated CDP session instead of Browser Harness's shared Chrome profile.
- Agent accepts that session. Host owns navigation, process lifetime, external budget and final evidence.
- Direct OpenAI text endpoints omit OpenRouter's reasoning parameter.
- Mouse input moves to the target before pressing; press/release events include the current button bitmask, matching the existing host executor.
- Observe visible labels for hidden checkbox/radio inputs, including checked state, and observed anchors/click/tabindex controls and custom controls with pointer cursors.
- Already-focused editable fields omit the redundant Open-field click action; TYPE_TEXT remains available. This prevents repeated no-op clicks in open editors.
- Formatting follows this repository. No per-click planner was added.

Upstream's flight demo is author-measured, not a general-purpose SOTA benchmark.

Further local reliability changes in v0.2.0.post3:
- Jev completion audit and at most three LLM recovery hints for uncertain/cycling decisions; Jev remains the action selector.
- Cross-field text context, paragraph word positions, current page/list positions, autocomplete metadata, nested scrolling, and hit-tested controls inside panels.
- Field-specific freshness guards preserve source-field changes without treating unrelated clocks as changes to the target.
- Async HTTP requests have a total cancellation deadline; text providers can fail over using only their own configured credentials.
- See docs/reliability.md for measured tradeoffs and retained failures.

Review fixes preserve full control state in completion audits, revalidate observed text sources before filling, interpret inactive ARIA current markers correctly, and make recovery hints optional on failure.
