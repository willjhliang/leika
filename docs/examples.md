# Examples

The runnable sources live in the repository's
[examples directory](https://github.com/willjhliang/leika/tree/main/examples).

- `python examples/basic.py`: live NumPy image plus a slider and a checkbox;
  base install.
- `python examples/showcase.py`: three named pages -- **Live signals** for a
  NumPy image and Plotly, **Analysis** for matplotlib, and **3D scene** for a
  viser scene -- driven by one shared GUI. It also demonstrates grouping,
  synchronized controls, callbacks, tabs, popup, modal, upload, command
  palette, notifications, GUI image/Plotly, and live updates; requires
  `leika[examples]`.

Each example prints a local URL. If Leika runs on a remote host, forward the
port over SSH and open the forwarded localhost URL.

[Panes](panes.md) explains the three-page model, the four pane types in the
showcase, and when to reach for each.
