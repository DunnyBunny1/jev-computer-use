# Lotus Jev core

A separately versioned Python package containing the adapted Jev Ultrafast decision/action loop used by Lotus. The import package is `jev_ultrafast`. It has no third-party runtime dependencies and includes its DOM snapshot script, MIT license, and [source provenance](UPSTREAM.md).

The host supplies an existing private browser session, installs `jev_ultrafast.model.RELAY` for decision and field-text requests, and owns deadlines, credentials, user control, and final summaries. The core never launches a browser or reads provider credentials. One process serves one task; relay configuration is process-local. Recovery requests are returned to the host, whose policy decides what happens next.

This package is independent of the repository's desktop application and its platform dependencies. Its initial release extracts the five core implementation files from LotusOS commit `bbc121fe1a36580ef7f0f06a0f9022a4c374c02a` and adds operation-confidence recovery, disabled-control evidence, ordered waiting and read/report completion guidance. Legitimate waits are excluded from action-loop detection; recovery execution belongs to the host.

Disabled controls retain safe current values, checkbox/radio state and read-only state as observation evidence without becoming executable actions. Observed link actions retain their absolute destination through the model's action space. Password, file and hidden inputs are excluded.

Interactive table headers are offered as click candidates when they expose a columnheader role or pointer cursor. Ordinary static headers remain text evidence.

Hosts can call `Browser.read_document()` for final-answer evidence covering rendered text and links outside the viewport. It excludes hidden/inert content and script/style/template text, returns at most 24,000 text characters and 200 links, and reports omitted text or links through `truncated`. Link destinations are limited to 4,096 characters and labels to 300. Fast decisions continue using viewport snapshots; the document reader neither scrolls nor executes input actions.

## Build and verify

From this package directory, build a wheel and source distribution using `uv build`. Run `python3 -m unittest discover -s tests` with Node.js available for the fixed DOM fixture; no browser, credentials, or inference are used. Install the wheel in an empty Python 3.12+ environment with `pip install --no-deps`, then import `jev_ultrafast.agent` from outside this source tree to check that the bundled snapshot is present.

## Release and consume

Release artifacts use the GitHub tag `lotus-jev-core-v` followed by the package version. Publish the wheel and source distribution from `dist/` on that release. The wheel is platform-independent (`py3-none-any`); it contains only this core, not the desktop application.

Lotus pins the version, wheel URL, and SHA-256 digest in its `device-runtime/retrieval/vendor/jev-core.lock.json`. Release builders download that exact wheel using pip's hash checking. Target installations use the bundled wheel offline with the same hash. Updates change this package's version and regenerate the Lotus pin after verifying the release wheel; they do not copy source into Lotus.
