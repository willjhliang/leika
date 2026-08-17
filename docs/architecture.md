# Architecture

Leika has one Python server and one generated, single-file React client.
HTTP serves the client bundle; a binary msgpack websocket carries typed
messages in both directions. Large payloads use zstd compression and uploads
are chunked.

The high-level Leika client and server negotiate an exact version and generated
protocol fingerprint as their WebSocket subprotocol. A low-level
`infra.WebsockServer` configured with a custom `Message` root instead accepts
ordinary clients without requiring Leika's bundled subprotocol. Either form
admits at most 128 active WebSocket clients per server instance.

The server binds to `0.0.0.0` by default and has no password unless one is
configured. Use `host="127.0.0.1"` for same-machine access, or set `password=`
and provide a protected transport when other machines can reach it. See
[Remote access](remote-access.md) for the complete security model.

## State flow

1. Python creates named pages, page-scoped panes, and workspace-wide GUI
   handles, then queues typed lifecycle messages.
2. Persistent messages are retained for clients that connect later. Repeated
   updates to the same entity/property key coalesce to the newest value.
3. The browser applies each received batch in order, displays its locally
   selected page, and keeps an independent pane layout for every page. GUI
   input changes update local state optimistically before the event is sent to
   Python.
4. Python updates the authoritative handle and broadcasts it to the other
   clients. The source client is excluded from that echo, preventing a fast
   slider from flickering through an older round-trip value.

Named pages partition the viewport state, not the whole application. The GUI
tree and control dock are workspace-global and stay mounted as the viewer
switches pages; updates for inactive pages continue to be retained.

`server.atomic()` is a queue-emission barrier: no message queued inside it is
emitted until the outermost context exits, and message order is preserved.
The result may then be split into several browser-safe transport windows, so
the context is not a browser transaction, an all-or-nothing operation, or a
delivery/render acknowledgement. `flush()` only requests an immediate outbound
window by bypassing the batching delay; it is not a delivery or render barrier.

Tab groups use an explicit flat lifecycle. The group declaration is retained
separately from stable tab create, update, and remove records, so every replay
prefix is valid and recursive removal retires both a descriptor and its GUI
subtree. This is an internal contract between the exact-version bundled client
and server, not a protocol-compatibility promise for custom low-level clients.

## Bounded Leika-owned state

Each `GuiApi` scope (`server.gui` or one `client.gui`) admits at most 4,096 live
components, 1,024 commands, 32 modals, and 128 notifications. A GUI graph is at
most 64 edges deep. One collection or tab group has at most 4,096 entries; one
scope retains at most 16,384 collection entries and 16,384 tab descriptors in
aggregate. Common renderer strings and collection entries are limited to
16,384 UTF-16 code units, while one `GuiText` value is limited to 1,048,576.
The scope-wide budgets are 16 Mi UTF-16 code units, 128 MiB of retained text
and binary payload, and 64 Mi-pixels. Notifications additionally share a
separate 2 Mi UTF-16 text ledger.

One connected browser document combines `server.gui` with its own `client.gui`,
and therefore admits at most 8,192 components, 2,048 commands, 64 modals, 256
notifications, 32,768 tabs and collection entries, 32 Mi UTF-16 code units, and
256 MiB of retained GUI payload. Notifications have a separate 4 Mi UTF-16
document ledger. Each handle retains at most 256 callbacks; connect and
disconnect lists retain at most 256 each. Programmatic GUI callbacks queue at
most 1,024 snapshots and 128 MiB before later callbacks are reported and
declined.

The workspace owns at most 128 named pages and, across all pages, at most 128
content panes, including hidden and minimized ones, and at most 16 Viser panes.
Pane sources share 32 Mi UTF-16 code units, 256 MiB of retained payload, and 64
Mi-pixels. Across all GUI scopes on one server, retained GUI state is capped at
256 MiB and GUI rasters at 128 Mi-pixels; `server.gui` and all workspace panes
additionally share a 64 Mi-pixel workspace-global raster ledger. The browser
counts every mounted copy of a direct raster against its own 128 Mi-pixel
document budget.

Image preparation has a separate 512 MiB server-wide envelope and charges four
times the source buffer, making 128 MiB the effective per-call ndarray source
ceiling. High-byte-depth arrays may need caller-side conversion to `uint8`.
These are ownership limits for Leika's GUI, pane, wire, and rendered state, not
a bound on total Python-process memory. Registered callbacks and lazy file
providers remain trusted caller-owned callables and may close over arbitrary
state.

Browser-to-server protocol messages are limited to 4 MiB. A server-to-browser
hybrid frame is limited to 512 MiB, including at most 256 MiB of metadata, 128
messages, and 16,384 binary buffers. The browser bounds the whole decoded
envelope to 500,000 values and depth 128, and validates it before applying any
message in that frame. Browser sends also stop at 16 MiB of WebSocket buffered
data, 8,192 throttled slots, or 1,024 uncoalesced events; overflow closes the
connection instead of silently dropping state.

Uploads are paced in acknowledged 512 KiB parts and capped at 64 MiB each.
The server's 256 MiB combined upload budget includes transfers in progress,
transient conversion headroom, and retained `UploadedFile` values; explicit
cancellation releases a transfer's reservation. The server admits at most 128
active uploads per server instance; each browser document independently admits
at most 128.

Runtime HTTP assets are capped at 64 MiB each and their immutable snapshot
cache at 128 MiB/1,024 entries. Static files are capped at 32 MiB each and
their cache at 32 MiB/128 entries. Across both paths, live response bodies
share a 128 MiB and 256-owner per-server budget; overload returns 503 with
`Retry-After: 1`.

Downloads are stream-flow-controlled to an 8 MiB queued budget per server
client, but browser save and link flows still assemble the complete file as a
Blob. The browser accepts at most 256 MiB and 65,536 parts per download, with
at most 128 active assemblies. One document-wide 512 MiB budget covers both
the declared bytes of active assemblies and completed Blobs retained by save
navigation, links, current or deferred previews, and the warm cache. Completion
transfers the reservation atomically to its Blob owner; under pressure,
lower-priority cache and link owners are evicted before a new transfer is
rejected. The same document admits at most 512 active or retained owners and
65,536 received part records in aggregate, including zero-byte and highly
fragmented transfers. These limits bound browser memory commitments; callers
should use a dedicated streaming endpoint for larger files.

A path-backed download is a live descriptor stream: atomically replacing the
path leaves an already-open transfer stable, while modifying the same file in
place can change bytes the transfer has not read yet. Pass immutable `bytes`
when the complete snapshot must be fixed at the time the download begins.

Plain-text, prose, and source previews render through 16 MiB; Markdown renders
through 1 MiB to bound parse and DOM expansion. The Blob remains available to
download when inline rendering is declined.

Plotly figure and theme-template JSON is parsed only through 16,777,216 UTF-16
code units (16 Mi-characters). Larger figures remain valid Python objects but
are declined with a visible browser status instead of expanding into an
unbounded JavaScript object graph.

GUI HTML is rendered through 1,048,576 UTF-16 code units (1 Mi-character), and
matplotlib SVG through 16,777,216 (16 Mi-characters). Larger sources are
declined before DOM, Blob, or image parsing and produce a visible status in the
affected control or pane.

Leika-owned image surfaces decode only verified, static PNG, JPEG, GIF, or WebP
rasters. Each side is limited to 16,384 pixels and the image to 33,554,432
decoded pixels. Animated, malformed, oversized, and unsupported files remain
available through an explicit link or download fallback rather than reaching
the browser image decoder. Markdown does not fetch external images; only a
bounded data image or the exact hash-and-dimensions URL emitted for a validated
Leika asset can render inline.

Plotly figures are preflighted through 500,000 values, configurations through
4,096 items, and the combined detached JSON snapshot through the size ceiling
above. A successful synchronous add or assignment stores its own snapshot, and
the public getter reconstructs an independent figure without consulting later
global-template changes. Exact Plotly figures and ndarray sources must not be
mutated concurrently while that snapshot is being taken.

The Plotly bounds do not sanitize renderer semantics: figures and configuration
remain trusted, server-authored input to a third-party renderer and may
intentionally reference external maps or images. Likewise, `GuiApi.add_html`
injects trusted raw HTML without sanitization; callers must sanitize untrusted
content first.

## Workspace ownership

Python owns page existence and names, pane existence and content, visibility,
and each pane's initial placement hint. The browser owns the selected page and
the user's arrangement within every page after that: splits, swaps, resizes,
floating state, and minimized panes. Selection is per viewer; changing it does
not send an event to Python or change what another viewer sees.

Pages scope only the visualization viewport. `server.gui`, each `client.gui`,
and the control dock's own position, size, and collapsed state are
workspace-global. Switching pages therefore changes the page name in the dock
header and the panes on the canvas without replacing the controls or moving the
dock.

Version-3 pane layouts are stored under a browser key containing the server
URL, `workspace_id`, and `page_id`. The selected `page_id` is stored separately
under the server URL and `workspace_id`, while the control dock keeps its own
workspace-level key. These namespaces avoid collisions between servers and
pages. Stable `page_id` and `pane_id` values let saved state recognize a page
and its panes after a Python restart; display names and pane titles may change
without changing layout identity.

The default page provides the compatibility bridge from the former one-page
model. If it has no version-3 layout, the client reads the version-2 layout for
the same server URL and `workspace_id`, normalizes it, and saves it under the
default page's version-3 key. Other pages never consume the old layout.

Public `workspace_id`, explicit `page_id`, and explicit `pane_id` values are
nonempty valid Unicode, at most 1,024 UTF-16 code units, and cannot be the
reserved JavaScript property names `__proto__`, `prototype`, or `constructor`.

Internally, an invisible root sentinel gives the dock manager a valid anchor
before any data pane exists. It is not a public pane and occupies no workspace
once visible panes are present.

## Scope

Leika is a simple data workspace. The client carries GUI, dock, layout, image,
SVG, and Plotly renderers, and CI checks that the shipped wheel and its browser
dependencies stay within that surface. Those renderers back the four pane
types in [Panes](panes.md). Matplotlib sources are held weakly, while ndarray
and Plotly assignments detach bounded snapshots as described above.

External Viser pages embed as intentionally unsandboxed iframes because their
clients require scripts, workers, and storage. They use a no-referrer policy,
and cross-origin browser isolation helps, but a same-origin target has the
Leika page's authority. Embed only trusted Viser clients and URLs. Leika ships
no 3D code and does not wrap other tools' applications.
