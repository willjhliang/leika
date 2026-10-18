# Changelog

Notable user-facing changes are recorded here. This project follows semantic
versioning.

## Unreleased

- GUI (breaking): overlapping controls are merged into one each.
  `add_list(..., mark="check" | "radio")` replaces `add_checklist()` and
  `add_radio_list()`, with `handle.marked` in place of `checked` and
  `selected`; `add_vector()` takes two or three components in place of
  `add_vector2()`/`add_vector3()`; `add_color()` takes an RGB or RGBA tuple in
  place of `add_rgb()`/`add_rgba()`; `add_folder(..., popup=True)` replaces
  `add_popup()`; `add_form(mini=True)` replaces `add_mini_form()`; and
  `add_toggle()` takes only a sequence of options, with `add_checkbox()` for a
  single true/false value. Their handles are `GuiListHandle`,
  `GuiVectorHandle`, `GuiColorHandle`, `GuiFolderHandle`, and
  `GuiToggleGroupHandle`.
- GUI (breaking): GUI elements are no longer limited (4,096 components per
  scope, 1,024 commands, 32 modals, 128 notifications, 64 levels of nesting,
  4,096 items per collection, 16,384-character labels and entries,
  1 Mi-character text and HTML, scope and server budgets, 256 callbacks per
  handle, a 256 MiB upload budget and 128 active uploads); browser input keeps
  its bounds, including the 64 MiB upload limit. A removed handle keeps its
  last state for reading and refuses updates and callbacks. Each property
  change is validated once and published in one message before it commits,
  and assigning a misspelled property, or a private one such as `_source`, now
  raises instead of setting a plain attribute. Programmatic callbacks run in
  the order the changes were made, without a queue cap. Slider `marks` and
  button and toggle `merge` are public properties.
- GUI: text inputs and list entries no longer stop at a browser-side length or
  entry count; each browser message is bounded by the 4 MiB inbound limit.
- GUI: a browser update other than a press no longer fires a button's
  `on_click`; disabling or hiding an upload button aborts an upload in flight;
  and a disabled or hidden preview button no longer reloads or watches its file.
- GUI (breaking): containers are filled only with `with container:`; the
  direct `folder.add_*(...)` methods are removed. Also removed:
  `leika.GuiTabGroup`, `GuiApi.set_panel_label()` (set
  `server.pages.default.name`), `GuiModalHandle.remove()` (use `close()`),
  `leika.DownloadContent` and `leika.PreviewContent` (use `FileContent`),
  `Server.add_notification()` and `ClientHandle.add_notification()` (use
  `.gui.add_notification()`), `GuiFormHandle.actions`, and
  `add_playback(sync_group=...)` (use `add_video_controls(sync_group=...)`).
- GUI: a form's Reset and Submit are drawn by the browser rather than added
  as a row of buttons, so children may use any order. A file button stays busy
  while it sends without changing its `disabled` property, and the progress
  bar is display only.
- Server: synchronous callbacks and deferred file transfers share one plain
  32-thread pool, without the 256-job pending cap. `stop()` called from a
  callback now waits for the server thread directly instead of handing the
  wait to a finalizer thread, and no longer clears registered connect and
  disconnect callbacks. The GUI and default page are queued before the server
  starts listening.
- File sends: `Server.send_file_download()` and `send_file_preview()` check
  their arguments once and send through each client's own path; inside an
  atomic block or on the event loop each client's transfer runs on the shared
  callback pool. Python no longer caps downloads at 256 MiB, 65,536 parts, or
  128 active transfers per client. Files, runtime HTTP assets, previews, and
  Markdown images are read with plain `open()`, so a FIFO or device path blocks
  as it would anywhere else, and `Path` subclasses are passed through as given.
- Panes (breaking): pages and panes are no longer limited to 128 pages, 128
  panes, 16 Viser panes, shared payload, text and raster budgets, or the
  16 Mi-character Matplotlib SVG limit; `server.stop()` leaves pane handles
  as they are instead of retiring them. `PaneHandle` is no longer generic,
  video URLs are no longer limited to 16,384 characters, and a removed pane
  keeps its last props.
- Panes (breaking): `Panes`, rows, columns, and grids share one set of `add_*`
  methods, which no longer take `placement` or `relative_to`, and
  `leika.Placement` is removed. A new pane splits off the latest visible pane;
  to start beside a particular pane, use `add_row(relative_to=...)` (to its
  right) or `add_column(relative_to=...)` (below it), which now raise
  `ValueError` at creation for an unknown or hidden pane.
- Viser: an embedded Viser 0.2 client loads its font through its pane's route
  instead of requesting it from Leika's root.
- Plotly: GUI plots now follow the viewer's light or dark theme like Plotly
  panes, through one shared serializer. Plotly's browser runtime is sent once
  to every browser after the first figure, including browsers viewing pages
  without one; a reconnecting browser keeps the runtime it already loaded.
  Figures are no longer preflighted (500,000 values, 4,096 config items,
  16 Mi-character JSON), any `go.Figure` subclass is accepted, and Plotly
  and Matplotlib serialization no longer take a server-wide lock.
- Images: GUI and pane images go through one preparation path that always
  encodes with Pillow, even when OpenCV is installed, using fast PNG
  compression (level 1) as OpenCV did. Image calls no longer
  enforce the 16,384-pixel side and 32 Mi-pixel limits or the 512 MiB
  server-wide preparation budget, and accept `numpy.ndarray` subclasses.
- Browser: the colour picker's remembered output format resets once, and
  command palette search ranks commands with cmdk's built-in matching.
- Browser: downloads and uploads no longer meet browser-side size, part or
  count limits or filename and MIME re-checks; uploads keep the server's limits.
  A file link toast now stays usable across a reconnect until it is closed.
- Browser: every image is decoded by the browser itself. Images are no longer
  header-checked or held to a page-wide pixel limit; one the browser cannot
  decode (including formats such as TIFF in a file preview) shows its ordinary
  broken-image state instead of a Leika status and download button.
- Browser: the client keeps its WebSocket on the page instead of a worker and
  applies each batch as it arrives, once per animation frame, instead of
  replaying the server's timing or closing the connection over its own queue
  and send limits.
- Browser: panes apply exactly as the server sends them, without browser pane
  limits; a cached page is no longer evicted early under memory pressure.
  Pane layouts saved by Leika 0.3 (version 2) are no longer migrated, so such
  a default page starts once from its creation-time placement.
- Browser: GUI controls, modals, commands and notifications apply exactly as
  the server sends them. The client no longer enforces its own count and size
  limits on them or drops the connection over them, and a notification shown
  again updates its toast in place.
- Transport (breaking): `leika.infra` is removed. The WebSocket and HTTP
  server is now private, with one message base; use `leika.Server`. Custom
  message roots and low-level servers are no longer supported.
- Server (breaking): `remove_client_connect_callback()` and
  `remove_client_disconnect_callback()` are removed, as are the 256-entry caps
  on connect and disconnect callbacks and on `allowed_hosts` (duplicate host
  names now collapse instead of raising).
- Server-to-browser messages are encoded once when queued and shared by every
  client, without outgoing size limits or HTTP response budgets; browser input
  stays bounded and validated. A page built from different code than the
  server is turned away with one "Protocol mismatch" reason that covers both
  the schema and the package version. The client page is served only at `/`.
- The `leika-build-client` console script and the `LEIKA_CLIENT_BUILD`
  environment variable are removed. A source checkout still rebuilds the
  browser client when its sources change, and `make build-client` builds it
  explicitly. Building needs `npm` on `PATH`; Leika no longer downloads Node.
  The sdist now carries the built client instead of its TypeScript sources,
  and no longer includes the documentation; change the client from a git
  checkout.
- Control panel (breaking): GUI tabs can no longer be torn out, reordered,
  stacked, or split; tab groups always render inline. The panel still floats,
  docks to the left or right edge, resizes its width, and collapses by clicking
  its header. Collapsed, it keeps that header in place of the side rail or the
  fade to the connection badge, and the phone's bottom sheet shares the same
  collapsed state. Each browser remembers the arrangement per server and
  `workspace_id`; `control_layout` places the panel until the viewer moves it.
  Saved panel layouts reset once.

- Support simulator environments pinned to WebSockets 12 and Pillow 11.3.
  One WebSockets server implementation uses the API available from version 12
  through 17, with no version dispatch or compatibility adapter.
  Native Viser panes support Viser 0.2.11 through the same authenticated port,
  including its worker assets. The proxy now uses HTTPcore instead of aiohttp;
  image decoding is restricted to Leika's PNG/JPEG formats.

- Each browser acknowledges a batch before it is sent the next from the same
  queue, so queued updates coalesce on slow connections instead of building up.
  `PaneHandle.has_viewers` lets producers skip hidden routine work.

- Markdown figures appear in document order as each image becomes ready,
  without waiting for later images. Reopened previews mount the first blocks
  before the rest of the cached document, keeping early figures responsive.

- Markdown previews reuse recent completed documents when reopened, while
  checking the source and linked images for changes. Unchanged documents skip
  another transfer, text decode, and parse; manual Reload still reads a fresh copy.
- Theme (breaking): replace `configure_theme(dark_mode=True/False)` with
  `configure_theme(theme="dark"/"light")`. The default `theme=None` is equivalent
  to `"auto"`. The API selects the Settings **Theme** option, and viewers can
  change it afterwards; **Auto** always follows the browser's OS preference.

## 0.4.0 — 2026-08-19

59 commits since v0.3.0. Items marked breaking need call sites updated.

### New

- Pages: `server.pages`, `Page`, and `Pages` add named canvases with independent
  layouts. Every server starts with a default page named by `Server(label=...)`;
  `server.panes` remains an exact alias for `server.pages.default.panes`.
- Radio lists: `GuiApi.add_radio_list()` and `GuiRadioListHandle` add editable or
  frozen, optionally labeled choices with at most one selection.
- Popups: `GuiApi.add_popup()` and `GuiPopupHandle` add a folder-like container
  whose controls stay behind one compact row until a viewer opens it.
- Pane loading: image, Matplotlib, Plotly, and Viser panes accept `loading=True`
  or status text, and `update(..., loading=False)` can reveal new content
  atomically.

### Improvements

- Client: the workspace, dock, controls, dialogs, panes, and previews now share
  one compact visual language and consistent focus and drag behavior.
- Docking: tabs reorder by their grips and can be torn into floating windows,
  redocked, or stacked. Double-click a torn-out tab's title to return it to its
  original group.
- Previews: dialogs open as soon as transfer metadata arrives, can fill the
  window, size media naturally, and remember whether each source uses full-window
  mode and shows a contents rail.
- Markdown: previews use GitHub-like typesetting, offer a contents rail that
  follows the current section, defer distant sections and media in long
  documents, and expand figures on demand.
- Controls: clipped labels, titles, choices, and unfocused fields reveal hidden
  text at a steady 40 pixels per second on hover. Editable fields yield to
  focus, and reduced-motion viewers jump directly to the end.
- Pages: each browser stores its selected page and per-page layouts locally,
  scoped by the server URL and stable `workspace_id`, `page_id`, and `pane_id`
  values. The default page imports a saved single-page layout from v0.3 when no
  current layout exists.
- Pages: pane payloads for inactive pages stay on the server, the browser keeps at
  most one completed page warm, and the persistent connection badge reads
  `Loading` while the selected page replays, even with the panel collapsed.
- API: `GuiPopupHandle`, `GuiRadioListHandle`, `NotificationHandle`, `Page`,
  `PageId`, `Pages`, and `PaneLoading` are available from the top-level `leika`
  package.
- Workspace chrome (breaking): the opt-in titlebar and `leika.theme`, including
  `TitlebarButton`, `TitlebarButtonConfig`, and `TitlebarButtonImage`, are gone.
  Compose a replacement header in the GUI; replace `control_layout="collapsible"`
  or `"fixed"` with `"left"` or `"right"`. `GuiApi.set_panel_label()` is now a
  compatibility alias that renames the default page, locally for `client.gui`.
- Remote access (breaking): Host and Origin validation protects against DNS
  rebinding. A wildcard bind trusts localhost spellings and IP-literal Host
  values only; list DNS, mDNS, and Tailscale names with
  `Server(allowed_hosts=[...])`. Forwarded headers are trusted only from the
  generated Cloudflare tunnel origin, and responses add `nosniff` and
  no-referrer policies.
- Embedding (breaking): `Server(allow_embedding=False)` is now the default and
  sends `Content-Security-Policy: frame-ancestors 'none'`. Notebook `show()` and
  other framed workspaces must opt in with `allow_embedding=True`.
- Python (breaking): Python 3.10 is now the minimum. The dependency minimums on
  supported Python versions exclude vulnerable Pillow and Pygments releases that
  older Python versions can no longer replace.
- Validation (breaking): public Python APIs stop silently coercing primitive
  values; booleans, strings, numbers, enums, and relevant NumPy arrays must have
  the documented types. Workspace, page, and pane IDs must be nonempty valid
  Unicode, at most 1,024 UTF-16 code units, and not `__proto__`, `prototype`, or
  `constructor`. A mini form requires exactly one direct editable field.
- Ports (breaking): a requested port is bound exactly instead of probing up to
  1,000 higher ports. Pass `port=0` for race-free automatic allocation and read
  the selected port from the running server.
- Resource limits (breaking): Leika-owned GUI, page, pane, raster, and protocol
  state is bounded at every scope instead of growing without limit. Headline caps
  are 128 active WebSocket clients per server, 4,096 live components per GUI,
  128 named pages and 128 panes per workspace, 16 Viser panes, and an effective
  128 MiB ndarray source per image-preparation call. The Architecture guide
  carries the complete table.
- Callbacks (breaking): callback lists and the programmatic callback queue are
  bounded. Button holds accept up to 64 requested rates, capped at 60 Hz; hold
  and client-connect/disconnect callbacks can now be removed explicitly.
- Notifications (breaking): auto-close now retires the server handle when the
  toast expires, and a successful update restarts its timer. Set `loading=True`
  or `auto_close_seconds=None` or `0` to suppress expiry.
- File providers (breaking): providers passed to `add_download_button()` and
  `add_preview_button()` must be synchronous. Complete asynchronous work before
  the press and return `bytes` or a `Path`; an awaitable result is rejected.
- Transfers (breaking): uploads are capped at 64 MiB per file, paced with
  acknowledgements, and cancellable. Downloads use an 8 MiB queued budget per
  client; browser assemblies are capped at 256 MiB, 65,536 parts, and 128 active
  assemblies. `chunk_size` is at most 8 MiB, filenames are validated, path
  sources must be regular files, and HTTP bodies have explicit server budgets.
  Sends made on the server event loop or inside `atomic()` are deferred and
  report path or transfer failures asynchronously.
- Rendering limits (breaking): Python rejects Plotly JSON and Matplotlib SVG above
  16 Mi UTF-16 code units, GUI HTML above 1 Mi UTF-16 code units, and oversized
  GUI or pane rasters before publication. Text, prose, and source previews render
  through 16 MiB and Markdown through 1 MiB. Refused file-preview and Markdown
  images remain downloadable, while Markdown no longer fetches external image
  URLs.
- Handles (breaking): removed GUI, pane, command, modal, and notification handles
  are terminal. Stable IDs remain readable; other synchronized operations raise,
  descendants retire recursively, and a repeated removal warns and does nothing.
- Batches (breaking): messages queued inside `server.atomic()` wait until the
  outermost context exits and keep their order, but may split into browser-safe
  windows. This is not a transaction or a delivery or rendering acknowledgment;
  `flush()` only bypasses the batching delay.
- Snapshots (breaking): successful ndarray and Plotly assignments store detached,
  bounded snapshots. Do not mutate those inputs concurrently during the call;
  Plotly getters return independent figures. Matplotlib sources are now weakly
  held, so retain the figure while using its pane handle.

### Fixes

- Connections: worker-local connection safety rejections now close cleanly; the
  client retries and keeps their diagnostic in connection details until it
  reconnects. Malformed browser messages are confined to the offending
  connection, while routine network closes remain silent.
- Pages: rapid switching no longer displays a stale page generation; reconnecting
  or refreshing restores the selected page and its layout.
- Images: live viewport, GUI, preview, and Matplotlib updates keep the previous
  frame visible until its replacement is decoded and admitted, eliminating blank
  flashes.
- Previews: an open preview follows its source file without reopening, scrolling
  no longer reloads it, and long Markdown documents keep headings and figures
  stable as deferred content settles.
- Lifecycle: disconnects release mounted GUI and pane resources before their
  shared browser budgets. Discarded preview jobs return their busy reservations,
  removed roots unlink from their registries, and shutdown retires cached assets
  and wakes blocked registrations.
- Panel: the collapsed page selector remains visible after selection, and the
  header keeps a stable row height while its status and controls change.
- Collections: frozen checklist and radio-list updates can change only check or
  selection state, not fixed labels, item counts, or ordering. In editable radio
  lists, arrow keys stay with the text caret; on a focused radio they navigate
  and select choices normally.
- Pane loading: opaque overlays stay above renderer controls and make underlying
  content inert.

### Misc

- Examples: the showcase keeps its simulation and Viser motion at 30 Hz while
  publishing coherent image and Plotly batches to Leika at 15 Hz.
- Docs: guides now cover pages, pane loading, and bounded state. The component
  gallery adds popups and radio lists and captures every component at 3× density.
- Notices: the production browser bundle carries complete generated third-party
  notices, and package validation requires them.
- Releases: one hash-constrained builder uses the tracked universal Python lock,
  builds twice for byte-for-byte reproducibility, and validates metadata,
  contents, provenance, and installation. Its validation-only Hatch hook never
  invokes Node, npm, or the network.
