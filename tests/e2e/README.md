# Browser tests

Build the client and install Chromium before running the Playwright suite:

```bash
cd src/leika/client
npm ci
npm run build
cd ../../..
python -m playwright install chromium
pytest tests/e2e
```

The suite uses only the built single-file client. It covers GUI rendering and
synchronization, fast slider release, multi-slider cancellation, multi-client
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
