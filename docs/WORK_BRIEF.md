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

## Decisions

- **Trust model.** Leika trusts its own server and Python caller. It validates
  and bounds only what browsers send to Python, and authenticates connections.
  Every resource ledger, budget, preflight, browser re-validation, image
  sniffing and pixel lease goes.
- **Client.** GUI tab tear-out goes: the docking library becomes one control
  panel that floats, docks left or right, resizes and collapses. The preview
  pipeline, hover-scroll text, contents rail, per-file preview memory,
  connection statistics and colour-picker extras stay.
- **Python API.** Overlapping controls merge into one control per concept and
  compatibility aliases go. Rendering presets, pane-size reporting, client
  pacing and the `delivery_backpressure` option go; backpressure is always on.
  `leika.infra` becomes private. `share=True` stays. `add_playback(duration=)`
  and `add_video_controls(sync_group=)` remain the two playback entry points.
- **Release.** Minimal flow: build the client, `python -m build`, one short
  archive check, `twine check`, install smoke tests and tag-triggered
  publishing.
- Babble's WebSockets 12, Pillow 11.3 and Viser 0.2.11 support stays.

## Authorized plan

Each wave's agents work in temporary worktrees with disjoint file ownership.
Each outcome is reviewed, validated and committed with its tests and docs.

1. **Wave 1 (merged into `main` at `d92d8b4`).** The transport is the private
   `leika._transport` with one `Message` base and encode-once broadcasts;
   the docking library is one control panel; development uses one pip
   environment, `make` targets, `scripts/generate.py` and the minimal release
   flow.
2. **Wave 2a, running.** Python server, panes and shared content helpers
   (ledgers and budgets out, one image preparation, one pane adder and content
   layer, one Plotly serializer and runtime delivery, server file sends through
   the client path). In parallel, the browser client (budgets and
   re-validation out, one receive path without pacing, one image component,
   one Plotly loader, batched GUI actions only, one dark-mode source, dead
   code).
3. **Wave 2b.** The Python GUI layer (ledger out, one validation per
   component, one update, lifecycle and callback implementation, upload
   pipeline, dead code). In parallel, rendering presets end to end
   (Python, messages, Settings, pane-size reporting, `delivery_backpressure`,
   the resize re-broadcast, Viser `_port`).
4. **Wave 3.** Merge overlapping controls end to end, with the aliases, and
   roll the API out to Babble, do_anything and lwm.
5. **Wave 4.** Make the docs describe current behavior, then run full
   validation (unit, browser, docs, package) and a final review.

Local work uses the `leika` conda environment (Python 3.13 and Node 24 from
conda-forge, Leika installed editable with
`pip install --isolated --index-url https://pypi.org/simple -e ".[dev]"`,
because the configured NVIDIA extra index does not resolve here; isolated
builds need `PIP_CONFIG_FILE=/dev/null`). Worktrees put their own `src` first
on `PYTHONPATH` and run `npm ci` in their own client directory. Chromium's NSS
libraries are unpacked under `~/.cache/leika-e2e-libs`; browser tests run with
`LD_LIBRARY_PATH` pointing at its `usr/lib/x86_64-linux-gnu`.

`dist/` in this checkout holds the wheel Babble's `docs/VIEWER.md` verifies by
SHA256, and `make package` empties `dist/`; build release checks into another
directory until Babble moves to a newer install.

After wave 1: 709 Python unit tests, 641 client tests and 216 browser tests
pass. `test_gui.py::test_plotly_size_is_checked_before_config_json_parse`
fails on its own; it pins the Plotly preflight that wave 2a removes.

Breaking API changes roll out to Babble, do_anything and lwm in the same
change.

## Next actions

Wave 2a is running: Python server and panes, and the browser client. Review
and merge both, then start wave 2b.
