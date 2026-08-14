# Changelog

Notable user-facing changes are recorded here. This project follows semantic
versioning.

## 0.4.0 — 2026-08-12

Leika 0.4.0 remains an alpha release while its pre-1.0 API and workspace
model continue to mature.

### Highlights

- Reworked the browser workspace and controls around the current shadcn/Base UI
  stack, with more reliable panes, previews, Plotly rendering, and uploads.
- Added generated, complete third-party notices for the production browser
  bundle and strengthened wheel/source-distribution validation.
- Added leika.NotificationHandle to the top-level public API.

### Security and robustness

- Added Host/Origin validation against DNS rebinding. A wildcard bind now
  accepts localhost spellings and IP-literal Host values only. DNS, mDNS, and
  Tailscale names must be listed with Server(allowed_hosts=[...]); entries are
  hostnames or IP literals without schemes, ports, paths, or wildcards.
- Added Server(allow_embedding=False). The default sends
  Content-Security-Policy: frame-ancestors 'none'; notebook show() callers
  must opt in with allow_embedding=True.
- Restricted trusted forwarded headers to the exact generated Cloudflare
  tunnel origin, and added nosniff and no-referrer response policies.
- Limited each server to 128 active WebSocket clients. The bundled Leika client
  still negotiates an exact version/protocol fingerprint; low-level
  `infra.WebsockServer` custom-message roots remain compatible with ordinary
  clients that do not offer a Leika subprotocol.
- Bounded each `GuiApi` scope to 4,096 live components, 1,024 commands,
  32 modals, 128 notifications, 16,384 aggregate collection entries and tab
  descriptors, 16 Mi UTF-16 text, 128 MiB retained payload, 64 Mi-pixels, and
  graph depth 64. One browser combines two such GUI scopes, with corresponding
  8,192/2,048/64/256 owner ceilings, 32,768 collection entries and tabs,
  32 Mi text, and 256 MiB retained payload. Notifications use separate 2 Mi
  per-scope and 4 Mi per-page text ledgers.
- Bounded a workspace to 128 retained panes (including hidden or minimized),
  16 Viser panes, 32 Mi UTF-16 source, 256 MiB retained payload, and
  64 Mi-pixels. Server-wide GUI state is limited to 256 MiB and 128 Mi-pixels;
  `server.gui` and workspace panes share a 64 Mi-pixel ledger. Mounted browser
  rasters share 128 Mi-pixels, counting every rendered copy.
- Added a 512 MiB server-wide image-preparation envelope that charges four
  times an ndarray's source bytes, for an effective 128 MiB per-call source
  ceiling. High-byte-depth arrays may need conversion to `uint8`.
- Limited browser-to-server protocol messages to 4 MiB. Server-to-browser
  hybrid frames are limited to 512 MiB, 256 MiB metadata, 128 messages,
  16,384 binary buffers, 500,000 decoded values, and depth 128. The browser
  validates the complete envelope before applying any frame side effect.
  Outbound browser queues also close on overflow instead of dropping state.
- Bounded uploads to 64 MiB per file and 256 MiB of combined in-progress,
  conversion, and retained `UploadedFile` memory, with acknowledged flow
  control and explicit cancellation. Bounded queued downloads to 8 MiB per
  client. Runtime HTTP assets are capped at 64 MiB each; their immutable
  snapshot cache is capped at 128 MiB and
  1,024 entries. Static files are capped at 32 MiB each, while their cache is
  capped at 32 MiB and 128 entries. Live HTTP response bodies share a 128 MiB
  and 256-owner per-server budget; overload receives `503 Service Unavailable`
  with `Retry-After: 1`.
- Bounded browser-assembled downloads to 256 MiB and 65,536 parts each, with
  at most 128 active assemblies. One page-wide 512 MiB budget now covers both
  declared bytes under assembly and completed Blobs retained by saves, links,
  previews, and the warm cache. Admission or cache/link eviction keeps that
  combined ownership bounded; a 512-owner and 65,536 aggregate received-part
  cap also covers zero-byte and fragmented transfers. Browser save/link flows
  still require the complete file as one Blob.
- Plain-text, prose, and source previews render through 16 MiB; Markdown renders
  through 1 MiB to bound parse and DOM expansion. The received Blob remains
  available to download when inline rendering is declined.
- Plotly figures and theme templates are parsed through 16,777,216 serialized
  UTF-16 code units. Larger payloads show a browser limit status before JSON
  parsing instead of expanding into an unbounded object graph.
- GUI HTML DOM source is capped at 1,048,576 UTF-16 code units and matplotlib
  SVG source at 16,777,216. Larger sources show a visible browser status before
  DOM, Blob, or image parsing.
- Leika-owned image surfaces now admit only verified static PNG, JPEG, GIF, and
  WebP rasters through 16,384 pixels per side and 33,554,432 decoded pixels.
  Animated, malformed, oversized, or unsupported content remains an explicit
  link/download fallback. Markdown no longer fetches external images and only
  renders bounded data images or dimension-matched validated Leika assets.
- Plotly's JavaScript runtime is loaded as a stable regular-file snapshot,
  requires valid UTF-8, and is capped at 32 MiB before browser delivery.
- The limits above cover Leika-owned GUI, pane, wire, and rendered state,
  not total Python-process memory. Registered callbacks and lazy file providers
  remain trusted caller-owned callables and can close over arbitrary state.
  Raw `GuiApi.add_html` remains deliberately unsanitized, and Viser clients
  run in an unsandboxed no-referrer iframe; pass only sanitized HTML and trusted
  Viser clients or URLs.

### Compatibility and migration

- Removed the opt-in titlebar and the leika.theme module
  (TitlebarButton, TitlebarButtonConfig, and TitlebarButtonImage). Remove
  titlebar_content= and compose any replacement header inside the GUI.
- GuiApi.configure_theme(control_layout=...) keeps "floating"; replace the old
  "collapsible" and "fixed" values with "left" or "right" to choose the initial
  dock position.
- Hostnames used to open a wildcard-bound server are no longer implicitly
  trusted. For example:

  ```python
  server = leika.Server(
      host="0.0.0.0",
      allowed_hosts=["demo.tailnet-name.ts.net", "camera.local"],
  )
  ```

  Existing localhost and direct IP-literal URLs continue to work without an
  allowlist. An explicit DNS bind accepts its own hostname.

- Python 3.10 is now the minimum supported version. Python 3.8 and 3.9 are
  end-of-life upstream and their final compatible Pillow/Pygments resolutions
  carry known vulnerabilities; Leika now declares the audited secure floors
  directly.

- Embedding a workspace in a notebook or other frame now requires
  allow_embedding=True.
- `workspace_id` and explicit `pane_id` values must now be nonempty valid
  Unicode, at most 1,024 UTF-16 code units, and not exactly `__proto__`,
  `prototype`, or `constructor`.
- A requested server port is now bound exactly. Earlier releases silently
  probed up to 1,000 higher ports when it was occupied; callers that want
  race-free automatic allocation should pass `port=0` and read the selected
  port from the running server.
- Uploads larger than 64 MiB are rejected instead of being retained
  unboundedly in server memory.
- Downloads exceeding the per-file, part-count, active-assembly, or combined
  memory caps are now rejected by the browser rather than retained unboundedly.
- A path-backed download now documents its live-descriptor semantics: atomic
  path replacement does not affect an open transfer, but in-place writes can
  affect unread bytes. Pass immutable `bytes` for a fixed eager snapshot.
- Plotly figures whose serialized JSON exceeds 16,777,216 UTF-16 code units no
  longer render in the browser; reduce/downsample the figure before sending it.
- GUI HTML above 1,048,576 UTF-16 code units and matplotlib SVG above
  16,777,216 no longer render in the browser. Simplify or rasterize oversized
  content before sending it.
- Static raster images above 16,384 pixels on either side or 33,554,432 decoded
  pixels, and animated PNG/GIF/WebP images, no longer render inline. Their safe
  link/download fallback remains available. Plotly stays a trusted
  server-authored third-party renderer and may fetch resources named by a
  figure; this direct-image policy does not sanitize Plotly schemas.
- Removed GUI, pane, command, modal, and notification handles are now
  terminal. Stable IDs remain readable, while other synchronized reads,
  updates, and new callbacks raise `RuntimeError`; recursive descendants are
  retired and retained payloads scrubbed. Repeated removal warns and is a
  harmless no-op.
- `server.atomic()` now explicitly guarantees only that queued messages wait
  for the outermost context to exit and retain order. It may split them into
  multiple browser-safe windows and is not transactional or a delivery/render
  acknowledgement. `flush()` only bypasses the batching delay.
- Mini forms require exactly one direct editable field. Sibling display rows,
  nested containers, and a second field are rejected before publication.
- Successful ndarray and Plotly assignments detach bounded snapshots; callers
  must not mutate those inputs concurrently during the synchronous operation.
  Plotly getters reconstruct independent figures and ignore later global
  template changes. Matplotlib pane sources are held weakly, so callers must
  retain the original figure.
- Tab groups now use an explicit flat create/update/remove lifecycle for
  prefix-safe replay. This is an internal bundled-client protocol change, not a
  compatibility promise for custom low-level protocol consumers.

### Release engineering

- Release artifacts now come from one hash-constrained builder, use a tracked
  universal Python lock, and are checked for metadata, integrity, provenance,
  and installability before publication.
- Added a validation-only Hatch build hook. It never invokes Node, npm, or
  the network: a normal checkout wheel requires a current bundle and points to
  `leika-build-client --force` or `make package`; editable and sdist builds
  remain clean-checkout capable, and wheel-from-sdist validates its bundled
  client without a checkout stamp.
