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

## Documentation

```bash
python -m pip install -e ".[docs]"
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

Unit tests must work without Plotly unless marked `plotly`. Package tests build
the wheel from a clean client artifact, require the browser bundle to be
present, reject files that do not belong in a release wheel, and enforce a
5,000,000-byte ceiling.

## Releases

Bump `__version__` in `src/leika/__init__.py`, rerun `python
sync_client_server.py`, then tag and publish a GitHub release:

```bash
git tag -a vX.Y.Z -m "vX.Y.Z"
git push origin vX.Y.Z
gh release create vX.Y.Z --title "vX.Y.Z"
```

Publishing the release runs `.github/workflows/package.yml`, which builds the
browser client and the distributions, checks the tag against the packaged
version, validates wheel contents and size, smoke-tests a base install and the
`examples` extra, and only then uploads to PyPI through Trusted Publishing.

PyPI releases are immutable. A version number cannot be reused even after a
release is deleted, so a mistake means moving to the next patch version.

## Browser tests

The Playwright suite runs against the built single-file client, so build it and
install Chromium before the first run:

```bash
make build-client
python -m playwright install chromium
```

`make test-e2e` covers GUI rendering and synchronization, fast slider release,
multi-slider cancellation, the color picker, modal dismissal, notifications,
the titlebar, light/dark theming, multi-client updates, image/Plotly pane
lifecycle, resizing and persistence, and responsive floating/mobile control
panels.

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

One file in `components/ui` is vendored rather than generated: `status.tsx`
comes from the separate shadcn.io collection and has no `shadcn add` path, so
refreshing it means copying from upstream again. Record any further vendored
component in `src/leika/_licenses/shadcn-io-PROVENANCE.md`; that notice is on
`scripts/check_wheel.py`'s required list, so the wheel must ship it.

## Generated protocol

Run `python sync_client_server.py` after changing message dataclasses or the
package version. CI uses `python sync_client_server.py --check` to reject
generated-file drift.
