# Panes

Panes are the workspace's content surfaces. Each one relays a visualization you
composed elsewhere: Leika transports it and gives it a place to live, but does
not draw it for you.

Python declares which panes exist, what they contain, and where they should
first appear. Everything the viewer does afterwards -- splitting, resizing,
tearing out, minimizing -- belongs to the browser and is persisted there. See
[Architecture](architecture.md#workspace-ownership) for how that split is kept.

## Pane types

| Call | Content | Reach for it when |
| --- | --- | --- |
| {meth}`~leika.Panes.add_image` | A NumPy array, encoded as PNG or JPEG | You have pixels: a camera frame, a render, a rasterized plot |
| {meth}`~leika.Panes.add_matplotlib` | A matplotlib figure, relayed as SVG | You already draw with matplotlib and want the figure as-is |
| {meth}`~leika.Panes.add_plotly` | A Plotly figure, kept interactive | The viewer should hover, zoom, or pan the chart |
| {meth}`~leika.Panes.add_viser` | A live [viser](https://github.com/nerfstudio-project/viser) 3D scene | You need a 3D scene; viser serves it and Leika embeds its client |

Only `add_plotly` requires its library at import time. `add_matplotlib` and
`add_viser` are duck-typed -- on `savefig` and on `get_port()`/`get_host()`
respectively -- so neither matplotlib nor viser is a Leika dependency.

### Images

```python
server.panes.add_image(frame, pane_id="camera", title="Live image", fit="fill")
```

`frame` is an RGB or RGBA array of shape `(height, width, 3|4)`. RGB is sent as
JPEG and RGBA as PNG unless you pass `format=` yourself.

### matplotlib figures

```python
figure, axes = plt.subplots()
axes.plot(x, y)
pane = server.panes.add_matplotlib(figure, title="Loss")
```

The figure travels as SVG, so resizing the pane rescales it crisply without
asking Python to redraw. It is a *picture* of a figure: no hover, no zoom, and
the axes do not reflow to the pane's shape. Reach for `add_plotly` when the
viewer needs to interact, or rasterize into `add_image` when a figure holds so
many marks that one SVG element per mark gets expensive.

### Plotly figures

```python
server.panes.add_plotly(figure, config={"displayModeBar": False})
```

A figure that never had a template assigned picks up one matched to the
viewer's light or dark theme; an explicit template is left alone. For large
scatters, Plotly's own `scattergl` traces render on the GPU.

### viser scenes

```python
viser_server = viser.ViserServer()
server.panes.add_viser(viser_server, title="Scene")
```

The pane embeds viser's own client, with its orbit controls and gizmos intact.
Build the controls with Leika's `server.gui.add_*` and mutate
`viser_server.scene` from their callbacks, and the Leika dock drives the 3D
scene. Because the viewer's browser connects to the viser port directly, remote
viewers need that port reachable too -- forward both over SSH.

## Updating a pane

Every `add_*` call returns a handle. `update()` replaces the content and keeps
the pane's identity, title, and the viewer's arrangement:

```python
pane = server.panes.add_image(render(0.0))
while True:
    pane.update(render(phase))
```

Handles also carry `visible` and `remove()`. Matplotlib and Plotly handles
expose the underlying `figure`, and assigning to it is the same as calling
`update()`.

## Layout

By default each new pane splits off the last visible one. `placement` and
`relative_to` steer that, and the row, column, and grid helpers divide space
equally instead:

```python
grid = server.panes.add_grid(columns=2)
grid.add_image(frame, pane_id="field", title="Field")
grid.add_plotly(figure, pane_id="signal", title="Signal")
```

These are creation-time hints only. Once the browser has a saved arrangement
for a pane, that arrangement wins on reload -- which is what makes a stable
`pane_id` worth setting: it is how a saved layout recognizes a pane after a
Python restart.
