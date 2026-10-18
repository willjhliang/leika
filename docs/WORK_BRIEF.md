---
orphan: true
---

# Leika work brief

## State

General playback is implemented and installed in Babble.
`gui.add_playback(duration=...)` is a Python-owned timeline;
`gui.add_video_controls(sync_group=...)` drives browser-local video clocks.
The installed Babble wheel is built from `e3a3015`; it still reports 0.4.0, so
identify it by revision and the wheel SHA256 recorded in
`build/playback-reconnect.json`. Babble's `docs/VIEWER.md` owns its installation.

Downstream consumers are Babble (`babble/viewer/app.py`), do_anything
(`do_anything/viewer/live_app.py`) and lwm (`scripts/visualiz*.py`). They use
basic inputs, folders, text/HTML, `add_playback`, `add_video_controls`,
`add_preview_button`, `add_viser`, `add_grid`/`add_video`, `atomic`,
`register_http_asset`, `password`, `allowed_hosts`, `configure_theme` and
`sleep_forever`. Babble's Isaac pins require WebSockets 12, Pillow 11.3 and
Viser 0.2.11 support.

## Simplification review

A full read-only review found the codebase about two to three times larger
than its job: 25k lines of Python package, 45k of client source, 48k of tests
and 3k of release scripts. Reviewer estimates, which overlap, put the result
of the recommended changes near half of today's size or less.

Root causes, in order of cost:

1. **Leika defends against its own server and caller.** Python, the HTTP layer
   and the browser each keep resource ledgers, budgets, preflights and
   re-validation of state the other side already validated. Examples: the GUI
   and pane ledgers (`_gui_resources.py`, `_panes.py`, `_server.py`), the image
   envelope, `client/src/guiLimits.ts`, raster pixel leases, the retained
   download budget, the pending-frame budget, `imageSafety.ts`, the 2,580-line
   generated browser validator, and 67 infra limit constants. The browser
   already executes server-sent JavaScript (`plotlyBootstrap.ts`), so these
   checks protect nothing.
2. **Speculative performance machinery.** Seven receive-side queue layers and a
   worker protocol, adaptive rendering presets, opt-in delivery backpressure
   that every bundled browser already forces on, an ndarray wire path no
   schema field uses, a warm page cache, and a file preview pipeline with
   streaming, warm prefetch, cache revalidation and a progressive Markdown
   worker.
3. **Overlapping features.** A general docking library (7.7k source, 4.9k test
   lines) hosts only the control panel and torn-out GUI tabs; overlapping
   controls (checkbox/toggle; dropdown/toggle/radio list; list/checklist/radio
   list; vector2/3; rgb/rgba; popup and mini form as separate entry points);
   two entry points for video playback; `share=True` tunnels.
4. **Duplicate implementations.** Image encoding five times; pane `add_*` at
   four layers plus two pane content layers; four `update()` and five
   lifecycle implementations in the GUI; validation repeated up to five times
   per value; three Plotly serializers and delivery paths; server and client
   copies of file sending and of the client lifecycle; Markdown parsed four
   ways and cached in seven places; image header parsing three times; two
   message bases; dark mode from two sources.
5. **Crash-safe tooling for local builds.** Transactional client publication
   with recovery (`_client_autobuild.py`), crash-safe `dist/` replacement, a
   release lock, double reproducible builds, hostile-archive checks, six fsync
   helpers, and three copies of the sdist file list.
6. **Docs that record history and limit tables** instead of current behavior,
   and dev-only code: 1.7k lines of playgrounds nothing builds or references.

Defects found:

- A pane resize in one browser re-queues the full image on the shared stream,
  so every viewer of that page receives it again (`_server.py:613-631`).
- `Server(delivery_backpressure=False)` has no effect for bundled browsers;
  their rendering settings force it on (`_server.py:654`).
- GUI Plotly figures skip the theme-template handling panes receive.
- `InsidePictureContext` is only provided as `false`, leaving a dead branch.
- The progress bar is classified as an input on the server.

## Proposed plan

Proposals awaiting the owner's decisions are kept apart from authorized work.
Nothing below is authorized yet.

Behavior-preserving phases:

1. Delete dead code: playgrounds and their HTML pages, `sheet.tsx`,
   `testGuiContext.ts`, `shallowObjectKeysEqual.ts`, Markdown inlining in
   `_markdown.py`, `await_async_errors`, Viser `_port`, the ndarray wire path,
   `TypeScriptAnnotationOverride`, unreachable single-message GUI actions and
   the dead branch of `AssignablePropsBase`.
2. One implementation per concept: one image preparation path, one pane adder
   and one pane content layer, one GUI handle base with one `update`, retire
   and callback path, one validation function per component, one Plotly
   serializer, one file-send path, one lifecycle owner (`Server`), one message
   base, one window generator, encode-once broadcasts.
3. One client receive path: synchronous decode, a plain per-frame queue and one
   dispatch `switch`; no generated runtime validator.
4. Tooling: one client build path, one generator entry point, `uv build` plus
   one short archive check, `twine check` and install smoke tests; CI calls
   Makefile targets; docs describe current behavior only, and this brief is
   excluded from published docs.

Decisions for the owner:

- Trust model: validate only browser input and authentication, removing every
  resource ledger and client re-validation.
- Client cuts: GUI tab tear-out, the preview pipeline (keep a minimal preview),
  hover-scroll text, the Markdown contents rail, per-file preview memory,
  connection stats, colour-picker extras.
- API cuts: merge overlapping controls, rendering presets and pacing,
  `share=True`, the public `leika.infra` surface, compatibility aliases.
- Release depth: whether reproducibility checks and hashed build constraints
  stay.

## Next actions

Present the review, record the owner's decisions here, then execute the
authorized phases in order, each committed with its tests and docs.
