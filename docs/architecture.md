# Architecture

Leika has one Python server and one generated, single-file React client.
HTTP serves the client bundle; a binary msgpack websocket carries typed
messages in both directions. Large payloads use zstd compression and uploads
are chunked.

The bundled client offers one protocol fingerprint, a hash of the package
version and the generated message schema, as its WebSocket subprotocol. The
server closes a connection whose fingerprint differs from its own with a
"Protocol mismatch" reason, so a page built from other code is turned away
instead of misreading messages. A server admits at most 128 active WebSocket
connections.

The server binds to `0.0.0.0` by default and has no password unless one is
configured. Use `host="127.0.0.1"` for same-machine access, or set `password=`
and provide a protected transport when other machines can reach it. See
[Remote access](remote-access.md) for the complete security model.

## Code organization

The public Python surface is collected in `leika/__init__.py`. Internal modules
follow ownership boundaries so a new renderer, transport policy, or state
transition has a clear home.

| Responsibility | Python modules |
| --- | --- |
| Workspace composition, client lifecycle, shared budgets, and broadcast operations | `_server.py` |
| One browser's GUI, rendering preferences, outgoing transfers, and transfer cancellation | `_client_handle.py` |
| Download limits, validation, and descriptor-backed chunk sources | `_downloads.py` |
| Bounded background jobs and captured-payload admission | `_executor.py` |
| GUI creation, callbacks, and synchronized handles | `_gui_api.py`, `_gui_handles.py`, `_notification_handle.py` |
| Page catalog, pane handles, and pane update transactions | `_pages.py`, `_panes.py` |
| Renderer preparation shared by GUI controls and panes | `_image_encoding.py`, `_plotly.py`, `_markdown.py` |
| Per-browser raster variants after transport coalescing | `_rendering.py` |
| Retained GUI/pane resource measurement | `_gui_resources.py` |
| Typed wire schema, its codec, and the generated client contract | `_messages.py`, `_transport/_typescript.py` |
| WebSocket lifecycle, dispatch, replay, and flow control | `_transport/_websocket.py`, `_transport/_message_buffer.py` |
| HTTP request policy, password gate, routing, assets, and the Viser proxy | `_transport/_http_security.py`, `_transport/_auth.py`, `_transport/_http.py`, `_transport/_http_assets.py`, `_transport/_viser_proxy.py` |
| Regular-file snapshots and display-name validation | `_file_transfer.py` |

`Server` composes the public APIs and shared resources. `ClientHandle` depends
on the server only for its instance's services and type annotations; the server
creates and retires clients. Renderer preparation and resource measurement do
not depend on GUI handles or pane registries. Both kinds of surface call those
shared helpers directly. Pane property setters use one transaction that
reserves the prospective resource cost, queues the update, and commits the
handle; a failed admission or queue restores the previous state and cost.

`leika._transport` is private. `Server` alone owns connect and disconnect
callbacks and shutdown; the transport runs one worker thread whose teardown
closes every message buffer, the Viser proxy, and the handler registry. Request
policy owns accepted host and proxy rules, and the HTTP handler serves the
single-file client from memory with a precomputed gzip copy, rereading it when
the file changes.

Every message type is a dataclass under the one `Message` base in
`_messages.py`. An outbound message is checked against its annotations and
encoded once when it is queued; each outgoing window frames those bytes, so a
broadcast is serialized once for every client. Only messages that a browser's
rendering preferences replace are encoded again. A browser's message is decoded
and validated against the schema before any handler sees it.

| Responsibility | Browser modules, relative to `client/src/` |
| --- | --- |
| Application composition and stable viewer ownership | `App.tsx`, `ViewerProvider.tsx`, `ViewerContext.ts` |
| GUI and viewport sessions with independently callable actions | `ControlPanel/GuiState.ts`, `viewport/ViewportState.ts` |
| Store subscriptions and React selectors | `store.ts` |
| Worker transport, ordered frame processing, and dispatch | `WebsocketClientWorker.ts`, `WebsocketInterface.tsx`, `MessageHandler.tsx`, `messageBatch.ts` |
| Workspace placement and pointer gestures | `viewport/ViewportWorkspace.tsx`, `viewport/layoutModel.ts`, `viewport/gridLayout.ts` |
| Pane chrome, loading state, and renderer selection | `viewport/ViewportPaneHost.tsx`, `viewport/ViewportPaneLoadingOverlay.tsx`, `viewport/ViewportPaneRenderer.tsx` |
| Image, Matplotlib, Plotly, and Viser rendering | The corresponding `viewport/Viewport*Renderer.tsx` modules |
| Browser-local video clocks, groups and media lifecycle | `viewport/videoPlayback.ts`; control-panel and fullscreen controls subscribe to the same controller |
| Control-panel placement and presentation | `ControlPanel/` |

`createGuiState()` and `createViewportState()` construct complete sessions
without mounting React. Their hooks own one session per mounted viewer, and
`ViewerProvider` owns the queues and transfer brokers alongside those sessions.
Views subscribe to state and invoke actions; the state engines can be tested
with the same actions and persistence adapters used by the application.

Generated message definitions, icons, and vendored UI primitives remain under
their existing generators. Build and release tooling remain separate from
runtime orchestration; see [Development](development.md) for their entry points.

## State flow

1. Python creates named pages, page-scoped panes, and workspace-wide GUI
   handles, then queues typed lifecycle messages.
2. Persistent messages are retained for clients that connect later. A queued
   message replaces an older one with the same redundancy key: lifecycle
   messages derive theirs from the entity, so repeated updates to the same
   properties coalesce to the newest value, and a removal purges its entity's
   retained messages. Other messages keep their order unless they declare a
   key.
3. Each browser receives workspace-global metadata and GUI state, but pane
   payloads only for its selected page. It applies each received batch in order
   and keeps an independent pane layout for every page.
4. Changing pages sends an internal, generation-tagged subscription. The
   server replays retained state for that page, then streams its live updates;
   stale frames from a rapid switch are rejected before browser preflight.
5. GUI input changes update local state optimistically before the event is sent
   to Python.
6. Python updates the authoritative handle and broadcasts it to the other
   clients. The source client is excluded from that echo, preventing a fast
   slider from flickering through an older round-trip value.

On a retryable connection loss, the viewport retains its displayed page in the
existing bounded transition slot while a fresh catalog and page stream replay.
Matching pane IDs and renderer sources keep their mounted browser elements,
including local video playback state and Viser's iframe. Replayed state remains
authoritative: removed panes disappear, changed sources update, and a different
server or workspace clears the retained page. Memory admission can evict the
snapshot under pressure. Transfers and GUI controls still reset per connection;
retained renderers keep their resource leases until replaced or unmounted.

Named pages partition the viewport state, not the whole application. The GUI
tree and control panel are workspace-global and stay mounted as the viewer
switches pages. Inactive-page pane state remains retained on the server, but its
payload is not serialized or sent to that browser until the page is selected.
The browser preserves every page's layout and may retain one inactive page's
detached source model as a bounded warm cache. That hidden cache has no renderer
DOM or Viser connection. During a switch exactly one stale model -- the cached
target, or the outgoing page on a cold miss -- may remain visibly mounted but
inert while the authoritative target replays into separate staging state.
Matching `Ready`
atomically promotes that state; resource pressure may evict the stale model and
temporarily expose the loading surface.

`server.atomic()` is a queue-emission barrier: no message queued inside it is
emitted until the outermost context exits, and message order is preserved.
The result may then be split into several transport windows, so
the context is not a browser transaction, an all-or-nothing operation, or a
delivery/render acknowledgement. `flush()` only requests an immediate outbound
window by bypassing the batching delay; it is not a delivery or render barrier.

For live streams, ``Server(delivery_backpressure=True)`` makes each outbound
producer wait for a WebSocket pong after sending its batch. Because the pong
follows that batch on the wire, only one batch per producer can be in flight;
updates waiting in the message buffer still coalesce to their newest values.
The two producers (connection-local and broadcast) and each connected client
advance independently. This limits stale frame buildup on slow links at the
cost of a round trip per batch. It acknowledges byte delivery, not rendering;
existing connection keepalive and shutdown retain ownership of timeouts.
The setting defaults to false, preserving existing transport behavior.

Tab groups use an explicit flat lifecycle. The group declaration is retained
separately from stable tab create, update, and remove records, so every replay
prefix is valid and recursive removal retires both a descriptor and its GUI
subtree. This is an internal contract between a server and the client built
from the same code.

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
document ledger. Each handle retains at most 256 callbacks. Programmatic GUI
callbacks queue at most 1,024 snapshots and 128 MiB before later callbacks are
reported and declined.

The workspace owns at most 128 named pages and, across all pages, at most 128
content panes, including hidden and minimized ones, and at most 16 Viser panes.
Pane sources share 32 Mi UTF-16 code units, 256 MiB of retained payload, and 64
Mi-pixels. Across all GUI scopes on one server, retained GUI state is capped at
256 MiB and GUI rasters at 128 Mi-pixels; `server.gui` and all workspace panes
additionally share a 64 Mi-pixel workspace-global raster ledger. The browser
counts every mounted copy of a direct raster against its own 128 Mi-pixel
document budget.

These are ownership limits for Leika's GUI, pane, wire, and rendered state, not
a bound on total Python-process memory. Registered callbacks and lazy file
providers remain trusted caller-owned callables and may close over arbitrary
state.

Browser-to-server protocol messages are limited to 4 MiB, and each decoded
message to 100,000 values, depth 64, and 4 MiB of strings and bytes. A
server-to-browser window carries at most 128 messages and takes no more once
its encoded messages pass 8 MiB. Browser sends also stop at 16 MiB of
WebSocket buffered data, 8,192 throttled slots, or 1,024 uncoalesced events;
overflow closes the connection instead of silently dropping state.

Uploads are paced in acknowledged 512 KiB parts and capped at 64 MiB each.
The server's 256 MiB combined upload budget includes transfers in progress,
transient conversion headroom, and retained `UploadedFile` values; explicit
cancellation releases a transfer's reservation. The server admits at most 128
active uploads per server instance; each browser document independently admits
at most 128.

Runtime HTTP assets are capped at 64 MiB each; their immutable snapshots
share 128 MiB, beyond which the oldest registrations are evicted and their URLs
answer 404.

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
place can change bytes the transfer has not read yet. Windows may refuse to
replace a path while this standard file handle remains open. Pass immutable
`bytes` when the complete snapshot must be fixed at the time the download
begins.

Plain-text, prose, and source previews render through 16 MiB; Markdown renders
through 1 MiB to bound parse and DOM expansion. The Blob remains available to
download when inline rendering is declined. Path-backed Markdown streams its
text first, then publishes validated image URLs in document order as each
snapshot becomes ready. Up to 128 early image resolutions belong to each text
stream (bounded source/asset URLs); stale streams cannot update a new preview.
The final transfer remains the complete downloadable document. Reopened cached
documents mount in batches of 96 blocks; following an internal link completes
mounting before resolving its target. Image decoding remains viewport-bound.

Plotly figure and theme-template JSON is parsed only through 16,777,216 UTF-16
code units (16 Mi-characters). Public creation, update, and assignment preflight
that bound and raise `ValueError` before publication. The bundled client repeats
the check and shows a visible status if a payload bypasses the Python boundary.

GUI HTML is rendered through 1,048,576 UTF-16 code units (1 Mi-character), and
Matplotlib SVG through 16,777,216 (16 Mi-characters). Public creation and update
raise `ValueError` before publishing a larger source. The bundled client also
declines an oversized payload before DOM, Blob, or image parsing and shows a
status in the affected control or pane.

A received file-preview, Markdown, or registered-asset image reaches the decoder
only after verification as a static PNG, JPEG, GIF, or WebP. Malformed,
animated, oversized, and unsupported files remain available through an explicit
link or download fallback. Local Markdown image paths resolve from the document
directory (or `add_text`'s `image_root`) with ordinary filesystem semantics,
including parent directories, absolute paths, and symlinks. This base directory
does not restrict which local images a document can reference.
Markdown does not fetch external images; only a
bounded data image or the exact hash-and-dimensions URL Leika emits for a
registered picture can render inline.

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
not change what another viewer sees. It sends only an internal transport
subscription so the server can route pane payloads; it does not dispatch a
Python application event or callback.

Pages scope only the visualization viewport. `server.gui`, each `client.gui`,
and the control panel's own placement, width, and collapsed state are
workspace-global. Switching pages therefore changes the page name in the panel
header and the panes on the canvas without replacing the controls or moving the
panel.

Version-3 pane layouts are stored under a browser key containing the server
URL, `workspace_id`, and `page_id`. The selected `page_id` is stored separately
under the server URL and `workspace_id`, and so is the control panel's
arrangement once the viewer moves, resizes, or collapses it; until then the
panel follows `configure_theme(control_layout=...)`. These namespaces avoid
collisions between servers and pages. Stable `page_id` and `pane_id` values let
saved state recognize a page and its panes after a Python restart; display names
and pane titles may change without changing layout identity.

The default page provides the compatibility bridge from the former one-page
model. If it has no version-3 layout, the client reads the version-2 layout for
the same server URL and `workspace_id`, normalizes it, and saves it under the
default page's version-3 key. Other pages never consume the old layout.

Public `workspace_id`, explicit `page_id`, and explicit `pane_id` values are
nonempty valid Unicode, at most 1,024 UTF-16 code units, and cannot be the
reserved JavaScript property names `__proto__`, `prototype`, or `constructor`.

Internally, an invisible root sentinel gives the pane layout a valid anchor
before any data pane exists. It is not a public pane and occupies no workspace
once visible panes are present.

Pane handles own stable identity and one replaceable content worker. Content
preparation runs before an atomic registry commit, which checks the captured
worker, admits the replacement resource cost, and then retires the old worker.
Placement declarations have their own replay lifecycle, preserving initial
layout order while renderer declarations replace their previous payloads and
updates. Empty content uses that same path and allocates no renderer.

## Scope

Leika is a simple data workspace. The client carries GUI, control panel, layout,
image, SVG, and Plotly renderers, and CI checks that the shipped wheel and its
browser dependencies stay within that surface. Those renderers back the four pane
types in [Panes](panes.md). Matplotlib sources are held weakly, while ndarray
and Plotly assignments detach bounded snapshots as described above.

External Viser pages embed as intentionally unsandboxed iframes because their
clients require scripts, workers, and storage. They use a no-referrer policy,
and cross-origin browser isolation helps, but a same-origin target has the
Leika page's authority. Embed only trusted Viser clients and URLs. Leika ships
no 3D code and does not wrap other tools' applications.
