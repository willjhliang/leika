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

Babble integrates the bar at5362e79 and has103tests passing. Its viewer caches the
current rollout's poses for seeking and looping; reset is a separate simulation
action. Ant rendered interaction and ABC control/focused-render checks pass.
The full ABC grid loaded but its SwiftShader screenshot exceeded60s. This is not
a desktop rendering performance measurement. The installed CPU preview remains
on8092 with the user's ABC checkpoint; temporary8093 is closed. Babble's own
work brief and browser receipts own the detailed integration state.

## Dependency compatibility and artifacts

The installed local0.4.0 wheel is built from772adb42249a19fd530da7eda86a2bf8d9a8a29a.
It retains compatibility with Isaac-owned WebSockets12/Pillow11.3 and Viser0.2.11.
All Babble package versions are unchanged and pip check passes. The development
guide owns [dependency support](development.md#pinned-simulator-environments).
A Python-only reconnect correction is validated and awaiting a rebuilt wheel
and Babble installation. Playback updates publish one full state, preventing
retained seek/duration deltas from replaying an invalid timeline after content
replacement. Python1014tests, type/lint/docs checks pass; the browser regression
covers repeated duration replacement and reconnect. No source was pushed.

`build/playback.json` records source revision, artifact hashes, validation and
installation. Its wheel SHA256 is
`3ad085a6febc686ff4da625d3b06b5eb5f3f8186bd09b717838fe29273a9491c`.
Two independent builds match byte-for-byte; archive validators and Twine pass.
The package still reports0.4.0 and differs from PyPI0.4.0, so identify the local
artifact by revision and hash. Babble's docs/VIEWER.md owns its installation steps.

The prior6271be3compatibility wheel and receipt are preserved in
`build/compatibility-6271be3/`. `build/compatibility.json` remains the historical
compatibility validation record. No test cleanup work remains.
