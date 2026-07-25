# Development

## Bootstrap

```bash
python -m pip install -e ".[dev]"
cd src/leika/client
npm ci
npm run build
```

The Python package serves `src/leika/client/build/index.html`. Use
`leika-build-client` or `make build-client` after changing browser source.

Node is pinned in `.nvmrc`, which CI reads through `setup-node`'s
`node-version-file`. Use that same version locally (`nvm use`, or point
`nodeenv` at it) before running any command that rewrites
`package-lock.json`. npm versions disagree about which optional transitive
packages belong in a lockfile, so regenerating it on an older npm silently
drops entries that CI's npm then rejects with a confusing
`npm ci` "package.json and package-lock.json are not in sync" error.

## Checks

```bash
make lint
make typecheck
make client-test
make test
make test-e2e
make package
```

Run the first four before opening a change; add `make test-e2e` for
browser-facing changes and `make package` for packaging changes.

Unit tests must work without Plotly unless marked `plotly`. Package tests build
the wheel from a clean client artifact, require the browser bundle to be
present, reject files that do not belong in a release wheel, and enforce a
5,000,000-byte ceiling.

## Browser tests

The Playwright suite runs against the built single-file client, so build it and
install Chromium before the first run:

```bash
make build-client
python -m playwright install chromium
```

`make test-e2e` covers GUI rendering and synchronization, fast slider release,
multi-slider cancellation, the color picker, notifications, multi-client
updates, image/Plotly pane lifecycle, resizing and persistence, and responsive
floating/mobile control panels.

`test_dock.py` covers the docking surface's pointer gestures. The dock's layout
model is unit-tested in TypeScript (`src/dock/*.test.ts`); the gesture
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
in `src/index.css`. Generated component source lives in
`src/leika/client/src/components/ui`. From the client directory, add or refresh
a component with the pinned CLI version:

```bash
npx --yes shadcn@4.14.1 add <component>
```

The `shadcn` package remains pinned because `src/index.css` imports its stock
Tailwind support stylesheet. When that version or preset changes, regenerate
the components and update the package, theme tokens, licenses, and provenance
together. Keep to this single component framework, and let Leika's domain
components compose the generated shadcn primitives directly rather than through
a wrapper layer.

## Generated protocol

Run `python sync_client_server.py` after changing message dataclasses or the
package version. CI uses `python sync_client_server.py --check` to reject
generated-file drift.
