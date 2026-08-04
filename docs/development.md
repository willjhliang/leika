# Development

## Bootstrap

```bash
make install   # or: python -m pip install -e ".[dev]" && leika-build-client
```

The Python package serves `src/leika/client/build/index.html`. `make help`
lists every target.

## Building the client

`leika-build-client` -- equivalently `make build-client` -- is the only way the
client is built. CI runs it, the bootstrap above runs it, and a server that
finds no usable build runs it for you. What a build *is* stays in the client's
`package.json`; the entry point only invokes `npm ci && npm run build`, so
there is no second definition to drift.

A build records the hash of the sources it came from in
`build/.leika-sources`, and is rebuilt when that no longer matches the tree.
Timestamps are not consulted: checkouts, cache restores, and pip all rewrite
them. The stamp is written only after a successful build, so an interrupted
one is rebuilt rather than served.

Set `LEIKA_CLIENT_BUILD` to control this from a script:

| Value | Effect |
| --- | --- |
| `auto` (default) | Build when the stamp does not match, unless `npm run dev` is running |
| `never` | Never build; serve whatever is in `build/` |
| `always` | Build unconditionally |

Node is pinned in `src/leika/client/.nvmrc`, beside the `package.json` it
applies to, and CI reads the same file through `setup-node`'s
`node-version-file`. If that exact version is already on your `PATH` the build
uses it; otherwise it downloads a private copy with `nodeenv`.

Use that same version (`nvm use`) before running any command that rewrites
`package-lock.json`. npm versions disagree about which optional transitive
packages belong in a lockfile, so regenerating it on an older npm silently
drops entries that CI's npm then rejects with a confusing
`npm ci` "package.json and package-lock.json are not in sync" error. Builds
themselves use `npm ci` and never rewrite the lockfile.

## Checks

```bash
make lint
make typecheck
make client-test
make test
python scripts/check_docs.py
make test-e2e
make package
```

Run the first five before opening a change; add `make test-e2e` for
browser-facing changes and `make package` for packaging changes.
`check_docs.py` resolves every local Markdown link and compiles every shipped
example. It has no `make` target but CI runs it, so skipping it locally is a
way to go red on a broken link.

Unit tests must work without the optional plotting libraries unless marked
`plotly` or `matplotlib`. `make package` builds the distributions and validates
them with `scripts/check_wheel.py` and `scripts/check_sdist.py`: the browser
bundle must be present, files that do not belong in a release wheel are
rejected, and a 5,000,000-byte ceiling is enforced.

## Documentation

```bash
make install-docs   # or: python -m pip install -e ".[docs]"
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

Bump `__version__` in `src/leika/__init__.py`, rerun `python
sync_client_server.py`, then tag and publish a GitHub release:

```bash
git tag -a vX.Y.Z -m "vX.Y.Z"
git push origin vX.Y.Z
gh release create vX.Y.Z --title "vX.Y.Z"
```

Publishing the release runs `.github/workflows/package.yml`, which checks the
generated protocol and version, reruns the Python, client, docs, and browser
suites, builds the distributions, validates and smoke-tests both the wheel and
source archive, and only then uploads to PyPI through Trusted Publishing. Every
one of those gates blocks the upload, so a failing docs build stops the
release.

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
multi-slider cancellation, the color picker, checklists, markdown, download and
preview buttons, modal dismissal, notifications, the titlebar, icon buttons,
settings, the connection pane, light/dark theming, multi-client updates, the
lifecycle of every pane type, resizing and persistence, and responsive
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
a component with the pinned CLI version:

```bash
npx --yes shadcn@4.14.1 add <component>
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
component in `src/leika/_licenses/shadcn-io-PROVENANCE.md`; that notice is on
`scripts/check_wheel.py`'s required list, so the wheel must ship it.

## Generated protocol

Run `python sync_client_server.py` after changing message dataclasses or the
package version. CI uses `python sync_client_server.py --check` to reject
generated-file drift.
