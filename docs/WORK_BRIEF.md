---
orphan: true
---

# Dependency compatibility work

## Status and ownership

Leika's implementation and validation are complete at `6271be3`. The
[development guide](development.md#pinned-simulator-environments) owns dependency
support policy and implementation decisions. No further Leika changes are pending.

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
