---
orphan: true
---

# Dependency compatibility work

## Objective

Support Leika and native Viser panes in Babble's existing unified Python 3.11
environment, preserving Isaac Sim 5.1's pins. The handoff is
`/tmp/babble-leika-handoff.md`. Babble owns viewer and simulator integration;
shared environment changes require coordination with that owner. No GPU work,
simulator upgrade, publishing, or pushing is part of this task.

## Implementation

Compatibility is implemented in the canonical checkout, based on `5219898`.
The WebSockets 12 adapter translates HTTP hooks and subprotocol negotiation;
upstream owns parsing, framing and shutdown. The modern native server remains
the default on newer dependencies. HTTPcore replaces aiohttp in the proxy,
preserving the response-parser security floor without changing Isaac's aiohttp.
Pillow decoding explicitly accepts PNG/JPEG only. Viser stays optional.

Viser 0.2.11 is the selected legacy release. Its root-relative Vite asset and
worker URLs are rebased within the existing response budget. No simulator,
Viser source, or Leika browser-client patches are needed. The public
`ViserServer(host="127.0.0.1", port=...)` / `panes.add_viser(scene, ...)` API
is unchanged. Version support and security boundaries are documented in
[Development](development.md#pinned-simulator-environments).

## Validation

- Full Python suites: 1,106 passed on Python 3.13 with the modern lock, and
  1,106 passed on Python 3.10 with every declared direct dependency at its floor.
  The two gallery/message test assumptions exposed by the latter were corrected.
- Isaac pins on Python 3.11: 263 transport/image checks passed, plus the three
  added redirect/representation/shutdown regressions. The full 11-test proxy
  module also passes with the final rewrite-memory accounting.
- Real Chromium: four tests passed on both Viser 0.2.11/WebSockets 12 and
  Viser 1.0.30/WebSockets 16.1.1, including eight live scenes, geometry delivered
  after a Leika control action, and reconnect replay. Modern Viser retries on
  iframe focus; the old release also retries in the background.
- A normally installed wheel was tested under the Isaac pins, with `pip check`
  clean. No import-path or installed-metadata overrides were used.
- All 250 existing Babble package versions resolve unchanged. Its actual pip
  dry-run selects only Leika 0.4.0, Viser 0.2.11 and plyfile 1.1.3.
- Type checks, lint, changed-file formatting and strict documentation checks
  pass. The repository-wide format check flags pre-existing formatting in the
  untouched `tests/test_host_config.py`.
- The canonical release builder produces reproducible wheel/source archives
  and passes archive validation and strict Twine checks. The modern base
  dependency audit on Python 3.10 reports no known vulnerabilities.
- Logs are `/tmp/leika-*-*.log`. Browser commands use existing libraries from
  `/tmp/allegro-browser-deps/root/usr/lib/x86_64-linux-gnu` via command-local
  `LD_LIBRARY_PATH`. The previous shared browser cache revisions were restored.

## Installation handoff

Babble's unified environment is unchanged. The owner should coordinate its
installation and native Isaac coexistence check. No GPU validation was run here.
The local artifact still reports Leika 0.4.0; identify it by this source revision
and its wheel hash, not the different published PyPI 0.4.0 wheel.
`dist/compatibility.json` records the committed source and final artifact hashes.

The reviewed dependency snapshot is `/tmp/leika-babble-installed-constraints.txt`;
the exact resolver plan is `/tmp/leika-babble-install-plan.json`. After verifying
that snapshot is still current, the Babble owner can install the local wheel:

```bash
env -u PIP_INDEX_URL -u PIP_EXTRA_INDEX_URL -u PIP_TRUSTED_HOST \
  -u PIP_CONSTRAINT -u PIP_BUILD_CONSTRAINT PIP_CONFIG_FILE=/dev/null \
  /mnt/amlfs-01/shared/wiliang/miniconda3/envs/babble/bin/python -m pip install \
  -c /tmp/leika-babble-installed-constraints.txt \
  -c /mnt/amlfs-01/home/wiliang/leika/tests/constraints/isaac51.txt \
  /mnt/amlfs-01/home/wiliang/leika/dist/leika-0.4.0-py3-none-any.whl \
  'viser==0.2.11' 'plyfile==1.1.3'
/mnt/amlfs-01/shared/wiliang/miniconda3/envs/babble/bin/python -m pip check
```

Isaac retains Python 3.11, NumPy 1.26.0, Pillow 11.3.0, WebSockets 12.0,
aiohttp 3.11.11, typing-extensions 4.12.2 and Torch 2.7.0+cu128. HTTPcore 1.0.9,
h11 0.16.0 and AnyIO 4.14.2 are already present. Continue viewer implementation
and native simulator validation in Babble; no further Leika feature is proposed.
