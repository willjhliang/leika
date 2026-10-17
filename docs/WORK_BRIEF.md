---
orphan: true
---

# Leika work brief

## General playback

General playback is implemented and validated. `gui.add_playback(duration=...)`
returns a Python-controlled timeline with `time`, `playing`, `speed`, `loop`,
`fps`, `buffering`, atomic updates and optional `advance(seconds)` clock handling.
`on_update` receives browser commands with their original numeric intent and an
immutable state snapshot. Programmatic progress is silent. Python owns any
simulation, caching or rendering work; no background clock is started.

`gui.add_playback(sync_group=...)` uses the existing browser-local video clock.
Both adapters render the same full/compact control bar. `add_video_controls`
remains supported. The public behavior and example live in
[panes](panes.md#custom-playback) and [custom_playback.py](../examples/custom_playback.py).

Playback implementation is726e2db, command intent772adb4. The archive check now
requires the current artifact test file (da36a12). Validation passed1013Python
tests,907frontend tests,15existing video browser cases and a custom playback
browser case. Final event tests and24tests against Babble's installed simulator
pins pass. Locked type checks, Ruff, ESLint, TypeScript, docs, gallery and
reproducible wheel/sdist checks pass. Both interface layouts were visually checked.

Babble7c8f5e0 uses warm CPU workers, retires obsolete Viser geometry, and keeps
its timeline state valid across environment replacement.107Babbletests pass;
staging browser checks cover CPU switches, steps, pending-selection replacement,
full/balanced detail, fresh reconnect and the rendered ABC grid. Babble's work
brief owns the live preview identity and selection. Native Isaac processes still
restart on selection changes; no new GPU validation was run for this correction.

## Dependency compatibility and artifacts

The installed local0.4.0 wheel is built frome3a3015de8e8db271aec734400f22866c7397708.
It retains compatibility with Isaac-owned WebSockets12/Pillow11.3 and Viser0.2.11.
All Babble package versions are unchanged and pip check passes. The development
guide owns [dependency support](development.md#pinned-simulator-environments).
Playback publishes one complete state, preventing retained seek/duration deltas
from replaying an invalid timeline after content replacement. The correction is
committed, reproducibly packaged and installed in Babble.1014Python tests,
2browser playback tests and5tests against the installed simulator pins pass;
type, lint, docs and archive checks pass. No source was pushed.

`build/playback-reconnect.json` records source, artifact hashes and validation.
Its wheel SHA256 is
`7e2780977e104a36e1a233668ceeac1828227e956d5a306a1e5738c5e7298950`.
Two independent builds match byte-for-byte; archive validators and Twine pass.
The package still reports0.4.0 and differs from PyPI0.4.0, so identify the local
artifact by revision and hash. Babble's docs/VIEWER.md owns its installation steps.

The prior6271be3compatibility wheel and receipt are preserved in
`build/compatibility-6271be3/`. `build/compatibility.json` remains the historical
compatibility validation record. No test cleanup work remains.
