# Changelog

Notable user-facing changes are recorded here. This project follows semantic
versioning.

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
