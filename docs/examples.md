# Examples

Examples can be found on [Github](https://github.com/willjhliang/leika).

- `python examples/basic.py`: live NumPy image plus a slider and a checkbox;
  base install.
- `python examples/showcase.py`: image and Plotly panes (including a live 3D
  surface), grouping, synchronized controls, callbacks, tabs, modal,
  upload, command palette, notifications, GUI image/Plotly, and live
  updates; requires `leika[examples]`.
- `python examples/viser_scene.py`: the Leika dock driving a live viser 3D
  scene embedded as a pane; requires `leika[examples]`.

Each example prints a local URL. If Leika runs on a remote host, forward the
port over SSH and open the forwarded localhost URL.
