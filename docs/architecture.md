# Architecture

Leika has one Python server and one generated, single-file React client.
HTTP serves the client bundle; a binary msgpack websocket carries typed
messages in both directions. Large payloads use zstd compression and uploads
are chunked.

The server has no authentication and binds to `0.0.0.0` by default. Bind to a
trusted interface or put Leika behind an authenticated reverse proxy when it is
not strictly local.

## State flow

1. Python creates panes and GUI handles and queues typed lifecycle messages.
2. Persistent messages are retained for clients that connect later. Repeated
   updates to the same entity/property key coalesce to the newest value.
3. The browser applies each received batch in order. GUI input changes update
   local state optimistically before the event is sent to Python.
4. Python updates the authoritative handle and broadcasts it to the other
   clients. The source client is excluded from that echo, preventing a fast
   slider from flickering through an older round-trip value.

`server.atomic()` holds a logical group in one outbound batch. `flush()` is a
delivery barrier, not a browser-render barrier.

## Workspace ownership

Python owns pane existence, content, visibility, and the initial placement
hint. The browser owns the user's arrangement after that: splits, swaps,
resizes, floating state, and minimized panes.

Layouts are stored under a versioned browser key containing the server URL and
`workspace_id`. This avoids collisions between servers, and bumping the version
retires saved layouts that the current client can no longer read. Stable
`pane_id`s allow a saved layout to recognize panes after a Python restart.

Internally, an invisible root sentinel gives the dock manager a valid anchor
before any data pane exists. It is not a public pane and occupies no workspace
once visible panes are present.

## Scope

Leika is a simple data workspace. The client carries GUI, dock, layout, image,
SVG, and Plotly renderers, and CI checks that the shipped wheel and its browser
dependencies stay within that surface. External pages — viser 3D
scenes — embed as iframes of their own clients; Leika ships no 3D code. Other
tools' own applications are theirs to serve: Leika does not wrap them.
