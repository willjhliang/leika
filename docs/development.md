# Development

## Environment

Develop in one environment with Python 3.10 or newer and Node.js 24, for
example a conda environment:

```bash
conda create -n leika -c conda-forge python=3.13 nodejs=24
conda activate leika
make install   # pip install -e ".[dev]", then build the browser client
```

Every Make target runs its tools from the active environment; `make help`
lists them.

## Building the client

The server serves `src/leika/client/build/index.html`. In a source checkout, a
server that finds that build missing or older than the client sources rebuilds
it before starting; `make build-client` does the same explicitly. A build runs
`npm ci` when `package-lock.json` changed since the last install, then the
client's own `npm run build`, and records a hash of the client sources in
`build/.leika-sources`. It needs `npm` from Node.js 24 on `PATH`. The Hatch
build hook builds the client the same way into every sdist and wheel, so an
installed wheel ships the build and never rebuilds it.

Node is pinned in `src/leika/client/.nvmrc`, which CI reads through
`setup-node`. Use that npm major version before running any command that
rewrites `package-lock.json`: npm versions disagree about which optional
transitive packages belong in a lockfile, and `npm ci` rejects a lockfile an
older npm wrote.

## Generated files

Run `make generate` after changing message dataclasses, the package version,
or the pinned `lucide-static` version. It regenerates the TypeScript protocol,
the client's version file, and the `leika.Icon` enum and SVG archive.
`make check-generated` fails instead of writing when any of them is out of
date.

## Checks

```bash
make lint
make typecheck
make client-test
make test
make docs
make test-e2e
make package
make gallery  # After visual client or gallery-registry changes.
```

Run through `make docs` before opening a change; add `make test-e2e` for
browser-facing changes and `make package` for packaging changes. CI runs these
targets on every pull request.

Unit tests must work without the optional plotting libraries unless marked
`plotly` or `matplotlib`. `make package` builds the sdist and wheel into
`dist/`, each with the built client and without its sources, and checks them
with `scripts/check_dist.py` and `twine check --strict`.

## Browser tests

The Playwright suite runs against the built single-file client, which it builds
when stale. Install Chromium before the first run:

```bash
python -m playwright install chromium
```

`make test-e2e` covers GUI rendering and synchronization, fast slider release,
multi-slider cancellation, the color picker, lists, markdown, download and
preview buttons, modal dismissal, notifications, settings, the connection pane,
light/dark theming, multi-client updates, the lifecycle of every pane type,
resizing and persistence, and responsive floating/mobile control panels.

`test_control_panel.py` covers the desktop control panel's pointer gestures --
floating, docking to either edge, resizing, collapsing, drag cancellation -- and
its persistence, which read real DOM geometry and so can only be verified in a
browser. The persistence rules themselves are unit-tested in TypeScript
(`src/leika/client/src/ControlPanel/controlPanelLayout.test.ts`).

Failure artifacts are written under `test-results/` when capture is enabled by
the local pytest-playwright configuration or CI runner.

## Documentation

Sphinx renders `docs/` into `docs/_build/html` through `make docs`, which first
runs `scripts/check_docs.py` to validate local Markdown and reStructuredText
links and compile every example and Markdown Python block. The narrative pages
are Markdown through MyST so they stay readable on GitHub; the API reference
under `docs/api/` is reStructuredText driven by autodoc, so public docstrings
are the only source for it. The build uses `-W`, which turns warnings such as a
broken cross-reference into failures, and CI publishes `main` to GitHub Pages
through `.github/workflows/docs.yml`. `make linkcheck` checks external links;
CI runs it weekly.

Adding a public class or method to `leika` means adding it to the matching page
in `docs/api/`; autodoc will not discover it otherwise.

## Minimum supported versions

Babble runs Leika inside Isaac Sim 5.1, which pins WebSockets 12, Pillow 11.3
and Viser 0.2.11; those are Leika's floors in `pyproject.toml`. Leika uses the
WebSockets 12 server API, `websockets.legacy.server`, on every supported
WebSockets release; upstream maintains that API until November 2029 under its
[migration policy](https://websockets.readthedocs.io/en/stable/howto/upgrade.html).
Leika opens images only as PNG or JPEG, which keeps it clear of the decoders
with known vulnerabilities in old Pillow releases. To reproduce the simulator's
versions:

```bash
python -m pip install -c tests/constraints/isaac51.txt -e ".[dev]"
python -m pip check
```

CI's minimum-versions job does this on Python 3.10, then runs the unit tests
and the Viser pane browser tests.

## Client UI

Interactive controls and app chrome use the stock shadcn/ui Base/Nova preset on
Base UI. The checked-in `src/leika/client/components.json` pins that preset,
the neutral base color, and Lucide; Geist and the radius scale are theme tokens
in `src/leika/client/src/index.css`. Generated component source lives in
`src/leika/client/src/components/ui`. From the client directory, add or refresh
a component with the project-pinned CLI. Install the lockfile first with
`npm ci`; `npm exec --` then resolves only that local dependency instead of
downloading and executing a registry package ad hoc:

```bash
npm exec -- shadcn add <component>
```

The `shadcn` package remains pinned because `src/leika/client/src/index.css`
imports its stock Tailwind support stylesheet. When that version or preset
changes, regenerate the components and update the package, theme tokens,
licenses, and provenance together. Keep to this single component framework,
and let Leika's domain components compose the generated shadcn primitives
directly rather than through a wrapper layer.

One file in `components/ui` is vendored rather than generated: `status.tsx`
comes from the separate shadcn.io collection and has no `shadcn add` path, so
refreshing it means copying from upstream again. Record any further vendored
component in `src/leika/_licenses/shadcn-io-PROVENANCE.md`;
`scripts/check_dist.py` requires every notice in that directory in the wheel.

## Extending the implementation

Start with the ownership map in [Architecture](architecture.md#code-organization).
Keep `leika`'s top-level exports and documented method signatures as the public
boundary; consumers of internal helpers should import their owning module.

- For a new pane renderer, prepare and validate the source in a shared Python
  helper, publish a typed pane message, and add the browser renderer through
  `ViewportPaneRenderer.tsx`. Keep renderer lifecycle details out of workspace
  gestures and use the pane property transaction for synchronized updates.
- For GUI or viewport state transitions, add actions to the corresponding
  session factory. Unit tests can construct `createGuiState()` or
  `createViewportState(storage)` directly; use browser tests for mounting,
  rendering, gestures, and connection lifecycle.
- For HTTP changes, put host/origin decisions in `HttpRequestPolicy`, retained
  runtime content in `HttpAssetRegistry`, and response/static-file behavior in
  `HttpRequestHandler`. Preserve the owner's shutdown behavior.
- For new wire messages, update the Python schema, run `make generate`, and
  cover both replay and live dispatch.

## Releases

Bump `__version__` in `src/leika/__init__.py`, add the dated entry to
`CHANGELOG.md`, run `make generate` (the client's version file follows
`__version__`) and, after visual changes, `make gallery`. Commit the results,
run the checks above, then tag and publish a GitHub release:

```bash
git tag -a vX.Y.Z -m "vX.Y.Z"
git push origin vX.Y.Z
gh release create vX.Y.Z --title "vX.Y.Z"
```

Publishing the release runs `.github/workflows/package.yml`. It checks that the
tag is `v` followed by `leika.__version__`, runs `make package`, installs the
wheel and the sdist into fresh environments and serves the page from each, and
then uploads both to PyPI through Trusted Publishing. PyPI releases are
immutable: a mistake means moving to the next patch version.
