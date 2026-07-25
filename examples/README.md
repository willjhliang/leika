# Examples

Run these files from the repository root after installing Leika in editable
mode.

- `python examples/basic.py`: live NumPy image plus one slider; base install.
- `python examples/showcase.py`: image and Plotly panes, grouping, synchronized
  controls, callbacks, forms, tabs, modal, upload, command palette,
  notifications, GUI image/uPlot/Plotly, and live updates; requires
  `leika[plotly]`.

Each example prints a local URL. If Leika runs on a remote host, forward the
port over SSH and open the forwarded localhost URL.
