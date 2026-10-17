---
orphan: true
---

# Leika work brief

## General playback

The playback bar now supports custom Python content. `gui.add_playback(duration=...)`
provides a Python-owned timeline with command events and explicit progress;
`gui.add_playback(sync_group=...)` uses the existing browser video clock. Both
render one shared control component. Commands carry immutable state snapshots and the original numeric intent;
programmatic progress is silent. The application owns its clock and can use
`advance(seconds)` or publish simulation time directly. Existing video clocks
remain browser-local.

Validation: 1,013 Python tests, 907 frontend tests, 15 existing video browser
cases and one custom playback browser case pass. Locked type checking, Ruff,
ESLint, TypeScript, documentation and gallery generation pass. Full and compact
controls were inspected in light/dark themes. Packaging and Babble integration
are the next authorized actions; preserve the previous compatibility artifact.


## Test cleanup

Test cleanup is complete. Generated-protocol checks compile and execute the
TypeScript validator; packaging checks use real bundle files; lifecycle checks
verify collection of removed controls; iframe privacy checks inspect browser
requests. Tests for source snippets, helper-call choreography and duplicate
behavior were removed. Runtime code and dependencies are unchanged.

The retained suites contain 1,009 Python tests, 907 frontend tests and 238 browser
cases. Validation passed all Python and frontend tests plus 105 selected Chromium
cases covering the affected flows. TypeScript, ESLint, Ruff and documentation
checks passed. The generated-protocol execution test uses the existing frontend
toolchain and skips when that toolchain is absent.

No Leika cleanup work is pending. The Babble handoff remains with its owner below.

## Dependency compatibility status and ownership

Leika's implementation and validation are complete at `6271be3`. The
[development guide](development.md#pinned-simulator-environments) owns dependency
support policy and implementation decisions. No dependency implementation work is pending.

The Babble agent owns installation, viewer integration and native Isaac validation
under the original handoff, `/tmp/babble-leika-handoff.md`. This Leika task did not
modify Babble's shared environment or run GPU work. Publishing and pushing remain
outside its scope.

## Validation and artifacts

`build/compatibility.json` records the tested source revision, dependency versions,
test results, limitations, logs and artifact hashes. Preserve it and the tested
wheel, `dist/leika-0.4.0-py3-none-any.whl`, for the active Babble handoff. The local
artifact still reports version 0.4.0 but differs from the published PyPI wheel;
identify it by revision and hash. Temporary test environments are under `/tmp`.

## Installation handoff

The reviewed dependency snapshot is `/tmp/leika-babble-installed-constraints.txt`;
the resolver plan is `/tmp/leika-babble-install-plan.json`. The Babble owner should
verify that the snapshot is still current before installing the tested wheel:

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
