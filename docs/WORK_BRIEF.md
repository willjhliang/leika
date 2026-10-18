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
- **Release.** Minimal flow: build the client, `uv build`, one short archive
  check, `twine check`, install smoke tests and tag-triggered publishing.
- Babble's WebSockets 12, Pillow 11.3 and Viser 0.2.11 support stays.

## Authorized plan

Each wave's agents work in temporary worktrees with disjoint file ownership.
Each outcome is reviewed, validated and committed with its tests and docs.

1. **Wave 1, in parallel.** Release tooling and CI; the single control panel
   (with the dev playgrounds deleted); the private transport (one message base,
   encode-once broadcasts, one window generator, one lifecycle owner, in-memory
   client serving, no ndarray path, no generated browser validator, inbound-only
   limits).
2. **Wave 2.** Python server and panes, then the Python GUI layer: remove
   ledgers and budgets, one implementation per concept, dead code. In parallel,
   the browser client: remove budgets and re-validation, one receive path,
   one image component, one Plotly loader, dead code.
3. **Wave 3, in parallel.** Remove rendering presets end to end; merge
   overlapping controls end to end.
4. **Wave 4.** Make the docs describe current behavior, then run full
   validation (unit, browser, docs, package) and a final review.

Local work uses the `leika` conda environment (Python 3.13 and Node 24 from
conda-forge, Leika installed editable with pip from PyPI only, because the
configured NVIDIA extra index stalls). Worktrees put their own `src` first on
`PYTHONPATH` and run `npm ci` in their own client directory. Chromium's NSS
libraries are unpacked under `~/.cache/leika-e2e-libs`; browser tests run with
`LD_LIBRARY_PATH` pointing at its `usr/lib/x86_64-linux-gnu`.

Baseline before the work: 1,013 Python unit tests pass and one fails only
under parallel workers (it patches `json.loads` while Plotly loads its
validator cache); 907 client tests and 240 browser tests pass. In the conda
environment, `test_viser_pane.py::test_eight_live_scenes...` fails because it
decodes Viser's wire format and pip resolves Viser 1.1.1.

Breaking API changes roll out to Babble, do_anything and lwm in the same
change.

## Next actions

Wave 1 is running: release tooling and CI, the single control panel, and the
private transport.
