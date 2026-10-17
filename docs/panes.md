# Panes

Panes are the workspace's content surfaces. Each pane belongs to one named page
and relays a visualization you composed elsewhere: Leika transports it and
gives it a place to live, but does not draw it for you.

Python declares which pages and panes exist, what the panes contain, and where
they should first appear. Each viewer chooses a page and arranges its panes in
the browser. Those choices are persisted locally. See
[Architecture](architecture.md#workspace-ownership) for how that ownership is
split.

## Pages

Every server begins with a default page. It is named `Main` unless
`Server(label=...)` supplies another name; the server itself has no separate
visualization-wide title. The existing one-page API remains exact shorthand:
`server.panes` is `server.pages.default.panes`.

Add more pages through `server.pages` and place panes through the returned
page's `panes` API:

```python
with leika.Server(workspace_id="run", label="Live signals") as server:
    server.panes.add_image(frame, pane_id="camera")

    analysis = server.pages.add("Analysis", page_id="analysis")
    analysis.panes.add_plotly(figure, pane_id="loss")
```

A page's `name` is what viewers see in the dock-header selector. Its `page_id`
is the stable identity used for browser persistence, so renaming a page does
not discard its layout. Page names and IDs are each unique within a server:

```python
analysis.name = "Results"
```

Pass explicit `page_id` values when layouts should survive a Python restart;
otherwise `add()` generates UUIDs. Pane IDs are local to their page, so two
pages may both contain a pane called `summary`, but `relative_to` and the layout
helpers never cross a page boundary.

The selected page is browser-local: viewers can look at different pages of the
same running server, and their selections are restored independently. Pages
scope pane payload transport as well as pane layouts: a browser receives live
pane payloads only for its selected page. To avoid a blank canvas while a
switch replays, the browser keeps at most one inactive page's detached source
model as a warm cache. While hidden, that cache has no renderer DOM, decoded
raster/GPU resources, or Viser iframe. A cached target appears immediately with
its last received content; an uncached target leaves the
outgoing page visible. Either stale view is inert until a separately staged
replay reaches `Ready`, then the current model replaces it. The cache is
discarded if client safety budgets need the space, and every page's layout
remains preserved. `server.gui` and each client's GUI remain workspace-wide,
so the same controls stay available while viewers switch pages.

## Pane types

| Call                                | Content                                                         | Reach for it when                                                |
| ----------------------------------- | --------------------------------------------------------------- | ---------------------------------------------------------------- |
| {meth}`~leika.Panes.add_pane` | Empty, ready for any content | Reserve a slot before data is available |
| {meth}`~leika.Panes.add_image`      | A NumPy array, encoded as PNG or JPEG                           | You have pixels: a camera frame, a render, a rasterized plot     |
| {meth}`~leika.Panes.add_matplotlib` | A matplotlib figure, relayed as SVG                             | You already draw with matplotlib and want the figure as-is       |
| {meth}`~leika.Panes.add_plotly`     | A Plotly figure, kept interactive                               | The viewer should hover, zoom, or pan the chart                  |
| {meth}`~leika.Panes.add_video` | A saved video file or HTTP URL | You want local or synchronized browser playback |
| {meth}`~leika.Panes.add_viser`      | A live [viser](https://github.com/viser-project/viser) 3D scene | You need a 3D scene; viser serves it and Leika embeds its client |

Only `add_plotly` requires its library to be installed. `add_matplotlib` and
`add_viser` are duck-typed -- on `savefig` and on `get_port()`/`get_host()`
respectively -- so neither matplotlib nor viser is a Leika dependency.

### Empty panes and changing content

A pane's identity and arrangement are independent of its content. Reserve a
slot with `add_pane()` on `server.panes`, a row, column, or grid:

```python
pane = server.panes.add_pane(pane_id="preview", title="Preview")
pane.set_video(video_path, sync_group="episode", fps=30)
pane.clear()                     # Blank, with no video player or controls.
pane.set_image(frame)            # Same pane and browser arrangement.
```

Every pane handle supports `set_image`, `set_video`, `set_matplotlib`,
`set_plotly`, `set_viser`, and `clear`. The setters take the renderer settings
from the corresponding `add_*` method; title, visibility and placement stay
with the pane. `loading=None` preserves the current overlay; pass
`loading=False` to reveal prepared content in the same change.

Existing convenience methods remain unchanged:

```python
video = server.panes.add_video(video_path, sync_group="episode", fps=30)
video.update(next_video_path)
video.clear()
video.update(next_video_path)    # Restores the previous video settings.
```

Clearing releases source data and renderer resources while keeping the pane's
ID, layout, title, visibility, and input refresh bindings. An empty pane has
only the workspace background and optional title/loading overlay. It belongs
to no playback group. Replacing or clearing Viser unregisters its proxy route;
you still own the Viser server itself. Immutable HTTP assets remain subject to
the server's bounded asset cache.

Preparation that was already running for the previous content raises if it
tries to publish after replacement or removal. Applications still own selection
revisions for work they start outside Leika. A typed handle's `update` restores
its renderer after clearing; after switching to another kind, use `set_*` to
switch back explicitly. `remove()` permanently removes the pane itself.

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

Direct pane and GUI ndarray calls validate dimensions before encoding and raise
`ValueError` above 16,384 pixels per side or 33,554,432 decoded pixels.

Received file-preview, Markdown, and registered-asset images reach the browser
decoder only after verification as a static PNG, JPEG, GIF, or WebP. Animated,
malformed, oversized, and unsupported files remain downloadable instead of
rendering inline. Markdown avoids external image URLs; validated Leika assets
carry their measured dimensions in their registered URL.

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

Matplotlib SVG source is limited to 16,777,216 UTF-16 code units
(16 Mi-characters). Creation or update raises `ValueError` before publishing a
larger figure; simplify or rasterize it before sending.

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

Serialized Plotly source is limited to 16,777,216 UTF-16 code units
(16 Mi-characters), including the figure and theme template. Creation or update
raises `ValueError` before publishing a larger figure; downsample or simplify it
before sending.

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
viser_server = viser.ViserServer(host="127.0.0.1")
server.panes.add_viser(viser_server, title="Scene")
```

The pane embeds viser's own client, with its orbit controls and gizmos intact.
Build the controls with Leika's `server.gui.add_*` and mutate
`viser_server.scene` from their callbacks, and the Leika dock drives the 3D
scene. Server-object targets use a same-origin route through Leika. The same
password protects the embedded client, assets, and WebSocket, and SSH or public
tunnels need only Leika's port. Bind Viser to `127.0.0.1`; password-protected
workspaces reject Viser objects listening on a non-loopback interface.

Leika removes the route and closes its connections when the pane is removed or
repointed. You still own the Viser server and should stop it when finished.
Viser's independent sharing messages are blocked through the embedded route.
Explicit URL targets remain direct embeds and keep their own access policy.

The iframe is intentionally unsandboxed because the Viser client requires
scripts, workers, and storage, and it uses a no-referrer policy. Cross-origin
same-origin-policy isolation helps, but a same-origin target has the Leika
page's authority. Embed only trusted Viser clients and absolute URLs.

## Workspace limits

One workspace retains at most 128 named pages and, across all of them, at most
128 content panes, including hidden and minimized ones, and at most 16 Viser
panes. All page pane sources share 32 Mi UTF-16 code units, 256 MiB of retained
payload, and 64 Mi-pixels. These are Leika-owned state budgets rather than a
bound on the memory retained by caller objects or by trusted renderer code.

## Updating a pane

Every `add_*` call returns a handle. `update()` replaces the content and keeps
the pane's identity, title, and the viewer's arrangement:

```python
pane = server.panes.add_image(render(0.0))
while True:
    pane.update(render(phase))
```

Every pane also has a loading overlay. `True` shows the standard indicator, a
string adds status text, and `False` hides it. Set `loading` directly when only
the status changes:

```python
pane.loading = "Rendering next frame"
```

When new content and its loading state belong together, publish both through
one `update()` call. This keeps the previous renderer mounted behind the opaque
overlay, then reveals the replacement without an intermediate frame:

```python
pane = server.panes.add_image(placeholder, loading="Rendering first frame")
frame = render(phase)
pane.update(frame, loading=False)
```

The same `loading=` creation and update arguments are available on image,
video, matplotlib, Plotly, and Viser panes. Passing `None` to `update(..., loading=)`
leaves the current loading state unchanged.

For controls that replace the meaning of a pane, bind those inputs once:

```python
selector = server.gui.add_dropdown("Dataset", options=("train", "validation"))
pane.invalidate_on(selector)
```

The browser hides the old content as soon as an edit is queued, before GUI
throttling or network delivery. It accepts content again only when the update
includes the receipt for its latest edit. The callback must synchronously clear
obsolete server content, and background work must reject obsolete results. The
receipt also settles same-value and rejected edits; reconnecting restores the
server's current snapshot. Bind only live shared controls from this server.

### Rendering presets

The Settings gear contains **Rendering**, saved per browser and restored on
reconnect. It applies to native image panes, including paused images:

| Preset | Behavior |
| --- | --- |
| **Auto** (default) | Start at full source resolution, then adapt to measured connection throughput, preserving JPEG quality. Display size does not affect Auto. |
| **Performance** | Use half the display resolution in each dimension and JPEG quality 50 for smaller transfers. PNG stays lossless with alpha preserved, at the reduced resolution. |
| **Quality** | Send the application's original encoded image at full source resolution, without resizing or recompression. |

Auto uses smoothed bulk delivery receipts and the source image's byte size to
estimate a half-second transfer budget. It scales by pixel area, keeping at least
70% of each source dimension; this is a conservative heuristic, not a transfer-time
guarantee. Unknown or sufficiently fast connections receive original bytes, and
resolution recovers as faster receipts arrive. Very slow links also skip superseded
frames instead of reducing detail further. Small control messages do not change
the estimate; receipt timing includes round-trip delay.

No preset upscales the source. Auto retains JPEG quantization and chroma sampling
when resizing; unchanged-size Auto and Quality send the exact original bytes.
The source encoding comes from `format` and `jpeg_quality` (`85` by default),
so Quality cannot recover detail discarded by an application before publication.
PNG remains PNG in every mode. Vector plots, embedded Viser views, GUI images,
and document images retain their existing rendering paths.

Each browser receives its own encoding after queued updates coalesce. A viewer's
choice or slow connection does not lower another viewer's quality or cadence.
Switching presets or resizing a pane refreshes its current image even when the
application is paused. Application arrays and retained source images are unchanged.
Per-client resizing/encoding runs off the network event loop under the existing
server image-preparation budget. It adds CPU work when a variant is needed.

Browser rendering preferences automatically enable transport receipt backpressure.
`Server(delivery_backpressure=True)` remains available for non-browser clients.
`client.delivery_rate` reports smoothed bulk bytes received per second, including
round-trip delay, rather than the link's theoretical bandwidth. No preset changes
the application's source clock; a slow client receives fewer current frames.

Applications can check `pane.has_viewers` before expensive routine rendering.
Unknown browser dimensions count as visible; hidden panes and inactive pages do
not. Explicit selection and loading updates should still publish their new
content. `client.pane_size(pane)` remains available for custom layout work: physical
pixels, `(0, 0)` when hidden or on another page, and `None` until a size is known.

Updates apply whether or not the pane's page is currently selected. Switching
back shows the handle's latest retained content without creating another pane.
An inactive update is still prepared and retained by the Python server, but it
is not serialized into or compressed as an outbound frame for browsers viewing
other pages, nor decoded or stored by them. Page selection does not pause
caller-side queries or rendering work; an application that wants demand-driven
computation must still decide when to produce an update.

Setting `visible=False` removes a pane from the active page's layout while
retaining its renderer. Showing it again preserves the Viser iframe and native
video playback position and manual pause state. `remove()` disposes the renderer.
Inactive pages still follow the bounded page-cache lifecycle described above.

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

These are creation-time hints within the owning page only. Each page has an
independent saved arrangement, and that arrangement wins on reload. Stable
`page_id` and `pane_id` values let the browser match a page and its panes after
a Python restart; changing a display name or pane title does not change that
identity.

Pane boundaries snap to a 60-column by 60-row grid that fills the workspace.
Horizontal steps are 1/60 of its width and vertical steps are 1/60 of its
height, so equal full-axis splits into two through six panes align at any
aspect ratio. Focus a divider and use the arrow keys to move one step, or
Shift plus an arrow key to move four. Dense layouts expand the affected axis
in multiples of 60 when needed to keep every pane at least four columns wide
and three rows tall.

Page layouts use the version-3 browser store, keyed by server URL,
`workspace_id`, and `page_id`. When the default page has no version-3 layout,
Leika imports the prior version-2 single-page layout and writes it under the
default page's new key. Additional pages start with their declared placement
hints and never inherit that legacy layout.

## Native videos

Use `add_video` for one independent browser-native player. Python publishes its
source URL; the browser fetches and caches the media over HTTP. No video frames
are decoded or sent through the GUI connection by Python.

```python
from pathlib import Path
import leika

server = leika.Server()
pane = server.panes.add_video(Path("reach.mp4"), title="Reach")
pane.update(Path("grasp.mp4"), loading=False)
```

Compose a collection with the existing pane layout helpers:

```python
grid = server.panes.add_grid(columns=2)
for title, source in {"Reach": Path("reach.mp4"), "Grasp": Path("grasp.mp4")}.items():
    grid.add_video(source, title=title, autoplay=True, loop=True)
```

Each video is independently resizable and movable. A pane grid divides the
available workspace; it does not create a scrolling container. Titles use the
normal pane label, and the player fits its pane while preserving aspect ratio.

Sources may be local `Path` objects or absolute HTTP(S)/root-relative URL strings.
Local files use `register_http_asset`: immutable snapshots limited to 64 MiB per
file and 128 MiB across the server, with LRU retention. Serve larger collections
through an external media server. Browser codec support applies.

The compact playback bar uses Leika's theme and controls: play/pause, seeking,
elapsed/total time, playback speed, looping and fullscreen. It appears only while
the pointer is over the video pane; clicking or focusing a control does
not keep the bar visible after the pointer leaves. On touch devices it stays
visible. Fullscreen includes the video and its controls, including the speed
menu. Narrow panes show only elapsed time to keep the seek slider usable.
Set `fps=` to the media frame rate to enable previous/next frame buttons and
frame-sized seeking, for independent players as well as grouped videos.
Set `controls=False` to hide the bar. Controls operate locally in the browser,
independently for every pane, without Python callbacks.
Autoplay is muted to satisfy browser autoplay rules.
Offscreen players pause; manual pauses remain paused when returning to view.
An update with the same URL preserves playback; a different URL starts a new
player. Local assets support single byte-range requests for seeking; unsupported
multi-range requests receive the complete asset.

### Shared playback

A named group gives the videos on the displayed page one timeline in each
browser. The dock component and fullscreen overlays control that same timeline:

```python
server.gui.add_playback(sync_group="episode")
grid = server.panes.add_grid(columns=2)
for index in range(4):
    grid.add_video(
        Path(f"camera-{index}.mp4"),
        title=f"Camera {index}",
        sync_group="episode",
        fps=30,
    )
```

Without a label, the dock component is one full-width 32px row: play/pause,
previous/next frame, seek, elapsed time, speed and loop. Elapsed time stays
visible; hover over it for total duration. Pass a label, for example
`server.gui.add_playback("Playback", sync_group="episode")`, for a standard
24px labelled row containing only play/pause, seek, speed and loop. Both dock
layouts and video overlays use 12px gaps between icon bounds, text and the
timeline, with 24px button targets. The label
uses the same left column and styling as other GUI controls. Update
`controls.label` to switch layouts; `None` restores the full row.

The controller belongs to the viewer, independently of the dock's visibility.
Play/pause, seeking, speed and looping affect every group member; other browsers
keep their own playback state. The first declared member supplies initial
`autoplay` and `loop`. The longest clip sets the common duration, and shorter
clips hold their final frame until that timeline ends. Declare matching clips
with the same time origin; Leika does not infer timestamps or offsets.

Pass the same positive `fps` on every member to enable previous/next frame
buttons and frame-sized timeline steps. With unknown or differing rates, the
shared timeline still works but frame buttons are omitted. Stepping pauses the
group. This is time-based synchronization with drift correction, not a guarantee
of simultaneous frame presentation across browser decoders.

The group waits for visible members to load, seek or recover from buffering.
Hidden/minimized players pause individually and catch up when shown; hiding all
members or the browser tab freezes the common clock. A media error leaves the
group stopped with an error status. Replacing a source resets the common time to
zero while preserving the viewer's pause, speed and loop choices; updating the
same URL preserves position. Group names follow the pane-ID limits.

`pane.sync_group` and `pane.fps` are writable. Set `sync_group=None` on empty
placeholder panes so their duration does not affect the episode. Publish loading,
source and membership changes together with `server.atomic()`; the group waits
for loading members. In a group, a pane's hover bar fits just the fullscreen
button at the bottom right; fullscreen also exposes the shared playback controls.
With `sync_group=None`, the same controller drives the pane's independent hover
controls.


### Custom playback

The same bar can control arbitrary Python content. Pass `duration` instead of
`sync_group`; Leika does not require a video, Viser, or a simulator:

```python
playback = server.gui.add_playback(duration=10, fps=30)

@playback.on_update
async def changed(event: leika.PlaybackEvent):
    # A stable snapshot of this browser command, even if another thread advances.
    print(event.action, event.state.time)
```

Python owns the clock. Assign `playback.time` when content advances, or call
`state = playback.advance(elapsed_seconds)` in an application loop and render
`state.time`. The helper respects `playing`, `speed`, `loop`, `buffering` and
`disabled`; it stops at the final time when looping is off. It starts no thread.
See [the runnable example](../examples/custom_playback.py). A simulator can
publish its actual progress instead of using the helper.

Times and duration are seconds. Supply `fps` for previous/next frame buttons and
frame-sized seeking. Seek clamps to the duration, and frame stepping pauses.
Play at the end starts again at zero. Looping controls the clock; an application
owns frame caching or any simulation reset needed to realize the requested time.

`on_update` runs after an accepted browser command (`play`, `pause`, `seek`,
`step`, `speed` or `loop`). Regular functions run in the callback pool and async
functions run in the event loop. `event.state` is immutable. `event.value` retains the requested seek time, step
direction (-1/+1), or speed; other actions carry `None`. This lets asynchronous
applications queue relative steps even while a reset or seek is pending. Programmatic
assignments, `update(...)`, and `advance(...)` do **not** invoke callbacks, so
publishing progress cannot create an input feedback loop. For queued simulator
work, consume these events on the simulator's owning thread.

Publish related changes together, for example
`playback.update(time=0, duration=5, playing=False)`. `duration=0` disables the
transport until content is available. `buffering=True` announces preparation
while leaving pause and seek usable; `disabled=True` prevents all interaction.
Hiding the bar does not stop application work. Python-controlled state follows
normal GUI scope: `server.gui` is shared across browsers; `client.gui` is private.
Reconnect restores the published state. Video groups continue to keep independent
browser-local clocks; no frame-by-frame Python traffic is added to videos.

`add_video_controls(...)` remains available as the video-specific spelling of
`add_playback(sync_group=...)`. Video duration, autoplay, looping and frame rate
are still configured on video panes, not on their dock control.
