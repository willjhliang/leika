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

## Checks

```bash
make lint
make typecheck
make client-test
make test
make gallery  # After visual client or gallery-registry changes.
python scripts/check_docs.py
make docs
make test-e2e
make package
```

Run through `make docs` before opening a change; add `make test-e2e` for
browser-facing changes and `make package` for packaging changes.
`check_docs.py` recursively validates local Markdown and reStructuredText links,
then compiles every shipped example and Markdown Python block. It has no `make`
target but CI runs it, so skipping it locally is a way to go red on a broken
link or snippet.

Unit tests must work without the optional plotting libraries unless marked
`plotly` or `matplotlib`. `make package` builds the sdist and wheel into
`dist/`, each with the built client and without its sources, and checks them
with `scripts/check_dist.py` and `twine check --strict`.

## Pinned simulator environments

Leika uses the WebSockets 12 API on every supported version (12 through 17),
and supports Pillow 11.3 through 12.x. There is one server implementation,
imported explicitly from `websockets.legacy.server`, with native HTTP and
subprotocol hooks. Upstream owns parsing, framing and connection shutdown;
Leika owns request routing, response budgets and application policy. There is
no version detection or compatibility adapter.

The upstream legacy API remains available in newer releases but is deprecated
and maintained until November 2029. See the
[upstream migration policy](https://websockets.readthedocs.io/en/stable/howto/upgrade.html).
Leika's dependency range covers tested releases, not unbounded future versions.
The Viser proxy uses `httpcore[asyncio]>=1.0.9`, whose HTTP parser requires
`h11>=0.16`. Leika does not import or require aiohttp.

For Isaac Sim 5.1's Python 3.11 environment, install the source revision or its
locally built wheel with the checked-in compatibility constraints:

```bash
python -m pip install -c tests/constraints/isaac51.txt . viser
python -m pip check
```

This selects Viser 0.2.11, the last release before its WebSockets 13.1 minimum.
Viser remains optional. `ViserServer(host="127.0.0.1", port=...)` and
`server.panes.add_viser(scene, ...)` retain the same integration API. Legacy Vite
asset URLs, including worker URLs, stay inside the pane's proxy path; rewritten
HTML/JavaScript is fetched without compression and charged to the HTTP budget.
Other assets retain their encoding and range handling. Keep simulator-owned pins
in place; these constraints are test inputs, not a complete simulator lock.

The old Pillow release has known vulnerabilities outside Leika's image surface.
Leika only encodes and decodes PNG/JPEG and explicitly restricts `Image.open`
to those formats. This follows the format restriction in Pillow's
[FITS advisory](https://github.com/python-pillow/Pillow/security/advisories/GHSA-whj4-6x5x-4v2j)
and excludes the PSD/EPS decoders as well. It does not secure other applications
using Pillow. The proxy replacement preserves the reason for the former aiohttp
floor: its older C response parser has a
[memory safety advisory](https://github.com/aio-libs/aiohttp/security/advisories/GHSA-cq5v-8q36-5273).

CI runs the HTTP, auth, dispatch, resource/lifecycle and real-browser Viser tests
under the simulator pins, WebSockets 13 and the latest supported WebSockets,
alongside the locked environment. Viser's own dependency range determines which
Viser release can be installed with each transport version. No simulator
or GPU is required for these transport tests. The eight-scene browser test checks
geometry delivery, Leika controls, and reconnect replay on one forwarded port.
Viser owns reconnect policy: the tested modern version retries when its iframe
regains focus; Viser 0.2.11 retries in the background as well.

## Documentation

```bash
make docs
```

Sphinx renders `docs/` into `docs/_build/html`. The narrative pages are
Markdown through MyST so they stay readable on GitHub; the API reference under
`docs/api/` is reStructuredText driven by autodoc, so public docstrings are the
only source for it. `make docs` builds with `-W`, which turns warnings such as
a broken cross-reference into failures, and CI publishes `main` to GitHub Pages
through `.github/workflows/docs.yml`.

Adding a public class or method to `leika` means adding it to the matching page
in `docs/api/`; autodoc will not discover it otherwise.

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

## Browser tests

The Playwright suite runs against the built single-file client, so build it and
install Chromium before the first run:

```bash
make build-client
python -m playwright install chromium
```

`make test-e2e` covers GUI rendering and synchronization, fast slider release,
multi-slider cancellation, the color picker, checklists, markdown, download and
preview buttons, modal dismissal, notifications, settings, the connection pane,
light/dark theming, multi-client updates, the lifecycle of every pane type, resizing and persistence, and responsive
floating/mobile control panels.

`test_dock.py` covers the docking surface's pointer gestures. The dock's layout
model is unit-tested in TypeScript (`src/leika/client/src/dock/*.test.ts`); the gesture
controller and views above it read real DOM geometry, so they can only be
verified in a browser. Those tests drive the real app rather than a fixture:
the control panel is an ordinary dock panel and GUI tab groups are ordinary
dockable panels, so docking, splitting, snapping, tearing out, reordering,
resizing, minimizing, and drag cancellation are all reachable from it.

Failure artifacts are written under `test-results/` when capture is enabled by
the local pytest-playwright configuration or CI runner.

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
imports its stock Tailwind support stylesheet. When that version or preset changes, regenerate
the components and update the package, theme tokens, licenses, and provenance
together. Keep to this single component framework, and let Leika's domain
components compose the generated shadcn primitives directly rather than through
a wrapper layer.

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
  `HttpRequestHandler`. Preserve the owner's admission limits and shutdown behavior.
- For new wire messages, update the Python schema, regenerate the bundled
  TypeScript contract, and cover both replay and live dispatch. Resource
  reservations must be released on rejected publication as well as removal.

## Generated files

Run `make generate` after changing message dataclasses, the package version,
or the pinned `lucide-static` version. It regenerates the TypeScript protocol,
the client's version file, and the `leika.Icon` enum and SVG archive. CI runs
`make check-generated` to reject generated-file drift.
