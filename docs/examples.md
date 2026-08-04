# Examples

The runnable sources live in the repository's
[examples directory](https://github.com/willjhliang/leika/tree/main/examples).

- `python examples/basic.py`: live NumPy image plus a slider and a checkbox;
  base install.
- `python examples/showcase.py`: image, Plotly and viser panes (including a
  live 3D surface and a Leika-driven point cloud), grouping, synchronized
  controls, callbacks, tabs, modal, upload, command palette, notifications,
  GUI image/Plotly, and live updates; requires `leika[examples]`.

Each example prints a local URL. If Leika runs on a remote host, forward the
port over SSH and open the forwarded localhost URL.
