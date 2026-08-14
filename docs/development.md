# Development

## Bootstrap

```bash
make install   # Uses the tracked uv.lock.
# pip fallback: python -m pip install -e ".[dev]" && leika-build-client
```

The Python package serves `src/leika/client/build/index.html`. The Python-facing
Make targets run through the tracked `uv.lock`; `make help` lists every target.
The pip fallback honors published ranges instead of the development lock.

## Building the client

`leika-build-client` -- equivalently `make build-client` -- is the only way the
client is built. CI runs it, the bootstrap above runs it, and a server that
finds no usable build runs it for you. What a build *is* stays in the client's
`package.json`. The entry point resolves the pinned Node runtime, refreshes
dependencies with `npm ci` when the package inputs change, and then invokes
the package's `npm run build`; there is no second build definition to drift.

A build records the hash of the sources it came from in
`build/.leika-sources`, and is rebuilt when that no longer matches the tree.
Timestamps are not consulted: checkouts, cache restores, and pip all rewrite
them. A completed generation is staged and validated before an atomic directory
swap, so an interrupted build leaves either the previous generation or a
recoverable new one rather than a mixed bundle. Files and directory entries are
explicitly flushed on POSIX. Python does not expose directory fsync on Windows,
so there the backup transaction guarantees process-crash recovery while
power-loss durability remains the filesystem's responsibility.

Hatch's custom build hook is validation-only: it never starts Node, npm, or a
network request. A standard wheel built directly from a checkout fails fast if
the bundle is missing or stale and points to `leika-build-client --force` or
`make package`. Editable and sdist builds remain possible from a clean checkout.
When a wheel is built from an extracted sdist, the hook validates the complete
bundled client without requiring the checkout-only source stamp.

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
`npm ci` "package.json and package-lock.json are not in sync" error.
Dependency refreshes use `npm ci` and never rewrite the lockfile; release
packaging forces a clean refresh even when the local install stamp matches.

## Checks

```bash
make lint
make typecheck
make client-test
make test
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
`plotly` or `matplotlib`. `make package` builds the distributions and validates
them with `scripts/check_wheel.py` and `scripts/check_sdist.py`: the browser
bundle must be present, files that do not belong in a release wheel are
rejected, and archive size, shape, and integrity limits are enforced. The
universal `uv.lock` is tracked for repeatable development and CI across every
supported Python version; CI uses `--locked`, while a separate lowest-direct
job checks that the broad published lower bounds remain usable.

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

Before tagging, bump `__version__` in `src/leika/__init__.py`, add the dated
entry to `CHANGELOG.md`, regenerate the protocol/version file, run the normal
release checks, and build the canonical distributions:

```bash
python sync_client_server.py
make lint typecheck client-test test
npm audit --prefix src/leika/client --audit-level=moderate
npm audit --prefix src/leika/client --omit=dev --audit-level=moderate
for python in 3.10 3.14; do
  for extra in base examples; do
    python scripts/check_dependency_audit.py --python "$python" --extra "$extra"
  done
done
python scripts/check_docs.py
make docs
make test-e2e
make package
git tag -a vX.Y.Z -m "vX.Y.Z"
git push origin vX.Y.Z
gh release create vX.Y.Z --title "vX.Y.Z"
```

`make package` is the single release build path. It performs a fresh locked
`npm ci` and production client build, checks the generated protocol, builds
with hashed constraints, validates both archives plus `twine check --strict`,
and recoverably swaps `dist/` for the exact validated pair. Client freshness
matters because its bundle carries the server version and mismatches refuse to
connect. The npm and Python dependency audits above are also required because registry
advisory data is network-backed and intentionally not part of the artifact
builder. The Python audit compares the exact isolated installation with the
marker-selected locked export before querying advisories, for both the base and
user-installable examples dependency sets at the oldest and newest supported
Python versions.

Release packaging and the published package require Python 3.10 or newer.
Release commands require uv 0.12.3, enforced by `pyproject.toml`;
`uv self update 0.12.3` updates an older installation. When changing the
reviewed Hatchling pin in `build-constraints.in`, regenerate and commit the
complete hashed closure with the pinned build tool:

```bash
uvx uv@0.12.3 pip compile build-constraints.in \
  --generate-hashes --python-version 3.10 \
  --custom-compile-command \
  "uvx uv@0.12.3 pip compile build-constraints.in (see docs/development.md)" \
  --output-file build-constraints.txt
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
preview buttons, modal dismissal, notifications, icon buttons,
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
component in `src/leika/_licenses/shadcn-io-PROVENANCE.md`; that notice is on
`scripts/check_wheel.py`'s required list, so the wheel must ship it.

## Generated protocol

Run `python sync_client_server.py` after changing message dataclasses or the
package version. CI uses `python sync_client_server.py --check` to reject
generated-file drift.
