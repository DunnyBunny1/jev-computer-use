# Lotus Jev core

A separately versioned Python package containing the adapted Jev Ultrafast decision/action loop used by Lotus. The import package is `jev_ultrafast`. It has no third-party runtime dependencies and includes its DOM snapshot script, MIT license, and [source provenance](UPSTREAM.md).

The host supplies an existing private browser session, installs `jev_ultrafast.model.RELAY` for decision and field-text requests, and owns deadlines, credentials, user control, and final summaries. The core never launches a browser or reads provider credentials. One process serves one task; relay configuration is process-local. Recovery requests are returned to the host, whose policy decides what happens next.

This package is independent of the repository's desktop application and its platform dependencies. Its initial release extracts the five core implementation files from LotusOS commit `bbc121fe1a36580ef7f0f06a0f9022a4c374c02a` and adds operation-confidence recovery, disabled-control evidence, ordered waiting and read/report completion guidance. Legitimate waits are excluded from action-loop detection; recovery execution belongs to the host.

## Build and verify

From this package directory, build a wheel and source distribution using `uv build`. Run `python3 -m unittest discover -s tests` without a browser, credentials, or inference. Install the wheel in an empty Python 3.12+ environment with `pip install --no-deps`, then import `jev_ultrafast.agent` from outside this source tree to check that the bundled snapshot is present.

## Release and consume

Release artifacts use the GitHub tag `lotus-jev-core-v` followed by the package version. Publish the wheel and source distribution from `dist/` on that release. The wheel is platform-independent (`py3-none-any`); it contains only this core, not the desktop application.

Lotus pins the version, wheel URL, and SHA-256 digest in its `device-runtime/retrieval/vendor/jev-core.lock.json`. Release builders download that exact wheel using pip's hash checking. Target installations use the bundled wheel offline with the same hash. Updates change this package's version and regenerate the Lotus pin after verifying the release wheel; they do not copy source into Lotus.
