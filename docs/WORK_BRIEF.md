# Leika work brief

## State

`gui.add_playback(duration=...)` is a Python-owned timeline;
`gui.add_video_controls(sync_group=...)` drives browser-local video clocks.

Every consumer installs Leika the same way: a regular install of this checkout,
`leika @ file:///mnt/amlfs-01/home/wiliang/leika`, listed in the requirements
it installs from (Babble `requirements-viewer.txt`, do_anything
`requirements.txt`, lwm `requirements/overrides.txt` and its compiled lock).
All three were installed from `main` at `3f86560` and pass their viewer tests;
the version stays 0.4.0 until the user releases.

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
2. **Wave 2a (merged at `0a0edf9`).** Python server, panes and content helpers
   without ledgers (one image preparation, one pane adder and content handle,
   one Plotly serializer with a replayed runtime, file sends through each
   client); the browser client without budgets or re-validation (WebSocket on
   the main thread, one image component, one Plotly loader, one dark-mode
   hook, one `addPane`). 657 Python, 357 client, 209 browser tests pass.
3. **Wave 2b, running.** One agent: the Python GUI layer (ledger out, one
   update/validation/lifecycle path) plus merging overlapping controls end to
   end with the aliases. Beside it: rendering presets end to end (also
   pane-size reporting, `delivery_backpressure`, Viser `_port`, the frame
   `timestampSec`, and the root-pane sentinel if modest).
4. **Wave 4.** Make the docs describe current behavior, run full validation and
   a final review, then roll out to the consumers.

Open review notes for the final pass: rows, columns and grids accept then
reject `placement`/`relative_to` (shared adder signature);
`PlotlyComponent` still reports malformed server JSON and invalid aspects
(client re-validation); Viser 0.2.11 requests a font at the server root (a
cosmetic 404 outside the proxy path).

Local work uses the `leika` conda environment (Python 3.13 and Node 24 from
conda-forge, Leika installed editable with
`pip install --isolated --index-url https://pypi.org/simple -e ".[dev]"`,
because the configured NVIDIA extra index does not resolve here; isolated
builds need `PIP_CONFIG_FILE=/dev/null`). Worktrees put their own `src` first
on `PYTHONPATH` and run `npm ci` in their own client directory. Chromium's NSS
libraries are unpacked under `~/.cache/leika-e2e-libs`; browser tests run with
`LD_LIBRARY_PATH` pointing at its `usr/lib/x86_64-linux-gnu`.

Installs copy the code and built page, so merges here don't reach running
consumers until a rollout. A rollout runs with `main` committed and its client
build current (consumer envs have no npm): reinstall each project per its
install doc (lwm syncs with `--reinstall-package leika` and must keep its
Isaac pins, e.g. Pillow 11.2.1), run its viewer tests, and restart the
visualizers this session owns: lwm's Pilot jobs `jca01ef3ea83041812226`
(port 8080) and `jc296cbdff34a1a8b927c` (port 8083), and Babble's CPU viewer on
port 8092 (launch record in Babble's `runs/viewer-checks/`).

After wave 1: 709 Python unit tests, 641 client tests and 216 browser tests
pass. `test_gui.py::test_plotly_size_is_checked_before_config_json_parse`
fails on its own; it pins the Plotly preflight that wave 2a removes.

Breaking API changes roll out to Babble, do_anything and lwm in the same
change.

## Next actions

Wave 2b is running in two worktrees. Review and merge both, then wave 4.

Roll out to all three consumers after the final merge of this series.

The user asked to ration usage: fold the Python GUI cleanup and the control
merge into one agent (wave 2b), run presets removal beside it, review diffs
selectively, run the full checks once per merge, and keep the docs pass lean.
