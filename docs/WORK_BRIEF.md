---
orphan: true
---

# Leika work brief

## Test cleanup

Test cleanup is complete. The suite retains functional API, transport, resource
lifetime, state-transition and browser interaction coverage. Duplicate static
component renders, cosmetic geometry checks, helper-only docking checks, repeated
parameter grids and implementation-shape assertions were removed. Shared preview
assertions now check pointer access to the dialog. Container tests no longer need
Plotly, and text preflight tests compare against real JSON serialization.

The two passes removed 375 collected cases, including 285 in the deeper pass.
The suite now collects 1,049 Python unit, 926 frontend unit and 242 browser cases.
Runtime code and dependency support are unchanged. No test cleanup work is pending.

Validation passed: all retained Python and frontend unit cases and 128 selected
Chromium interaction cases. Four Python cases initially failed while automatic
client builds encountered unused test imports; they passed after those imports
were removed. Type checking, lint and formatting pass. Logs are under
`/tmp/leika-lean-*.log`; collection is in `/tmp/leika-lean-python-after.txt`.

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
