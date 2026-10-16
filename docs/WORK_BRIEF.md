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

Leika uses one implementation of the WebSockets 12 API on all supported
versions, imported directly from `websockets.legacy.server`. The version selector
and compatibility adapter are removed. Native protocol hooks own handshake
integration and subprotocol selection. HTTP routing and budgets remain in
`_http_server.py`; response security policy remains in `_http_security.py`.
Upstream owns parsing, framing and connection shutdown.

Declared WebSockets support is `>=12,<18`. The same code passes transport tests
on 12.0, 13.0, 16.1.1 and 17.2. No version tests or fallback implementations are
used. The upstream legacy API is deprecated and maintained until November 2029;
this is the explicit tradeoff for using one API across the supported versions.

HTTPcore remains the proxy HTTP client, Pillow decoding accepts PNG/JPEG, and
Viser remains optional. The proxy owns asset URL rebasing for embedded Viser
panes. The public `ViserServer(host="127.0.0.1", port=...)` /
`panes.add_viser(scene, ...)` integration remains unchanged. See
[Development](development.md#pinned-simulator-environments) for the support policy.

## Validation

- Full Python suites: 1,109 passed on the minimum direct dependencies
  (WebSockets 12.0), the modern lock (16.1.1), and the newest release (17.2).
- Transport/image suite: 269 passed on WebSockets 13.0 and 17.2, including native
  malformed-handshake responses, auth, resource budgets and lifecycle checks.
- Four real Chromium tests passed on each of WebSockets 13.0/Viser 0.2.11,
  WebSockets 16.1.1/Viser 1.0.30, and WebSockets 17.2/Viser 0.2.23. Each checks
  eight live scenes, Leika controls and reconnect replay. Pip checks pass in
  the normally resolved intermediate/newest environments.
- Type checking, lint and changed-file formatting pass. The untouched
  `tests/test_host_config.py` has a pre-existing repository-wide formatting
  failure. Documentation content and strict builds are part of the checks.
- Installed-wheel validation against Isaac pins, final source/artifact identity,
  archive validation and build results are recorded in `build/compatibility.json`.

Logs use `/tmp/leika-single-*.log`. Disposable test environments stay under
`/tmp`; they are not deployed viewer runtimes. Initial concurrent browser runs
hit an upstream old-Viser process-enumeration race (`psutil.NoSuchProcess`)
before the eight scenes started. Sequential runs passed without code changes;
no workaround for that upstream startup bug was added to Leika.

## Installation handoff

Babble's unified environment is unchanged. The owner should coordinate its
installation and native Isaac coexistence check. No GPU validation was run here.
The local artifact still reports Leika 0.4.0; identify it by this source revision
and its wheel hash, not the different published PyPI 0.4.0 wheel.
`build/compatibility.json` records the committed source and final artifact hashes.
The tested Isaac pairing remains WebSockets 12.0 and Viser 0.2.11. Modern Viser
currently requires WebSockets below 17; the resolver selects Viser 0.2.23 for
WebSockets 17.2. This is Viser's dependency constraint, not a second Leika path.

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
