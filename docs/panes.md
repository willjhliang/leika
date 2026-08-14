# Panes

Panes are the workspace's content surfaces. Each one relays a visualization you
composed elsewhere: Leika transports it and gives it a place to live, but does
not draw it for you.

Python declares which panes exist, what they contain, and where they should
first appear. Everything the viewer does afterwards -- splitting, resizing,
tearing out, minimizing -- belongs to the browser and is persisted there. See
[Architecture](architecture.md#workspace-ownership) for how that split is kept.

## Pane types

| Call                                | Content                                                         | Reach for it when                                                |
| ----------------------------------- | --------------------------------------------------------------- | ---------------------------------------------------------------- |
| {meth}`~leika.Panes.add_image`      | A NumPy array, encoded as PNG or JPEG                           | You have pixels: a camera frame, a render, a rasterized plot     |
| {meth}`~leika.Panes.add_matplotlib` | A matplotlib figure, relayed as SVG                             | You already draw with matplotlib and want the figure as-is       |
| {meth}`~leika.Panes.add_plotly`     | A Plotly figure, kept interactive                               | The viewer should hover, zoom, or pan the chart                  |
| {meth}`~leika.Panes.add_viser`      | A live [viser](https://github.com/viser-project/viser) 3D scene | You need a 3D scene; viser serves it and Leika embeds its client |

Only `add_plotly` requires its library to be installed. `add_matplotlib` and
`add_viser` are duck-typed -- on `savefig` and on `get_port()`/`get_host()`
respectively -- so neither matplotlib nor viser is a Leika dependency.

### Images

```python
server.panes.add_image(frame, pane_id="camera", title="Live image", fit="fill")
```

`frame` is an RGB or RGBA array of shape `(height, width, 3|4)`. RGB is sent as
JPEG and RGBA as PNG unless you pass `format=` yourself.

Image admission takes a synchronous private snapshot. Do not mutate the ndarray
concurrently with `add_image()`, `update()`, or an `image` assignment; after
the call succeeds, later caller mutations cannot change the stored pane.
Preparation charges four times the source buffer against a server-wide 512 MiB
envelope, so one ndarray source is effectively capped at 128 MiB. Convert
high-byte-depth arrays to `uint8` when necessary.

Leika checks an image before browser decoding and admits only static PNG, JPEG,
GIF, or WebP through 16,384 pixels per side and 33,554,432 decoded pixels.
Animated, malformed, oversized, and unsupported rasters are offered as an
explicit link or download instead of being rendered inline. The same policy
protects GUI images and file previews. Markdown additionally avoids fetching
external image URLs; validated Leika assets carry their measured dimensions in
their registered URL.

### matplotlib figures

```python
figure, axes = plt.subplots()
axes.plot(x, y)
pane = server.panes.add_matplotlib(figure, title="Loss")
```

The figure travels as SVG, so resizing the pane rescales it crisply without
asking Python to redraw. It is a _picture_ of a figure: no hover, no zoom, and
the axes do not reflow to the pane's shape. Reach for `add_plotly` when the
viewer needs to interact, or rasterize into `add_image` when a figure holds so
many marks that one SVG element per mark gets expensive.

Browser SVG rendering is limited to 16,777,216 UTF-16 code units
(16 Mi-characters). A larger figure is rejected before image parsing; simplify
or rasterize it before sending.

Leika keeps only a weak reference to the source figure. Retain the figure
yourself while you need to read or update it through the handle; if it is
collected, the rendered SVG remains visible but the handle cannot reconstruct
the source object.

### Plotly figures

```python
server.panes.add_plotly(figure, config={"displayModeBar": False})
```

A figure that never had a template assigned picks up one matched to the
viewer's light or dark theme; an explicit template is left alone. For large
scatters, Plotly's own `scattergl` traces render on the GPU.

Browser Plotly parsing is limited to 16,777,216 serialized UTF-16 code units
(16 Mi-characters), including the figure and theme template. Downsample or
simplify a larger figure before sending it.

Plotly figures and configuration are trusted server-authored input to Plotly
itself. They can intentionally refer to external maps or images through
Plotly's schemas; Leika's direct-image URL and raster checks do not sanitize
those third-party renderer fields.

The server loads Plotly's runtime source from a stable regular-file snapshot,
requires valid UTF-8, and caps that source at 32 MiB before sending it to a
client.

Adding or assigning a figure synchronously preflights at most 500,000 values and
4,096 configuration items, then stores bounded, detached JSON. Do not mutate an
exact Plotly figure concurrently while that snapshot is taken. A successful
call is independent of later caller mutation and of later changes to Plotly's
global default template; the handle's `figure` getter reconstructs a fresh,
independent figure on each read.

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

The iframe is intentionally unsandboxed because the Viser client requires
scripts, workers, and storage, and it uses a no-referrer policy. Cross-origin
same-origin-policy isolation helps, but a same-origin target has the Leika
page's authority. Embed only trusted Viser clients and absolute URLs.

## Workspace limits

One workspace retains at most 128 content panes, including hidden and minimized
ones, and at most 16 Viser panes. Their sources share 32 Mi UTF-16 code units,
256 MiB of retained payload, and 64 Mi-pixels. These are Leika-owned state
budgets rather than a bound on the memory retained by caller objects or by
trusted renderer code.

## Updating a pane

Every `add_*` call returns a handle. `update()` replaces the content and keeps
the pane's identity, title, and the viewer's arrangement:

```python
pane = server.panes.add_image(render(0.0))
while True:
    pane.update(render(phase))
```

Handles also carry `visible` and `remove()`. Matplotlib and Plotly handles
expose `figure` under the ownership rules above, and assigning to it is the
same as calling `update()`.

Removal is terminal and scrubs retained payloads. The stable `pane_id` remains
readable, but other synchronized reads, updates, and assignments raise
`RuntimeError`; repeating `remove()` emits a warning and is otherwise a
harmless no-op.

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
