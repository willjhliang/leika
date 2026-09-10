# Performance review

Reviewed and optimized on 2026-09-10 against baseline commit
1cd000aa174fda6aa3bb45e0da4167d301f6255e.

The improvements target repeated server scans, browser copies and validation,
unnecessary React updates, observer overhead, and temporary image allocations.
No dependencies or public API/protocol changes were required.

## Measured results

These are local synthetic CPU/allocation measurements, not end-to-end network
or page-load benchmarks. Python used 3.12.3 with NumPy 2.5.2; browser-code
microbenchmarks used Node 24.18.0. Actual gains depend on workspace size,
payloads, update rate, and client hardware.

| Workload | Before | After |
| --- | ---: | ---: |
| Enqueue 10,000 distinct retained messages | 6.795 s | 0.442 s |
| Replay 10,000 retained messages | 116.5 ms | 7.54 ms |
| Deliver 100 live windows with 10,000 retained messages | 276.6 ms | 9.57 ms |
| GUI preflight: 2,048 controls, 128 property updates | 50.92 ms | 0.916 ms |
| GUI preflight for a download-only frame with 2,048 controls | 44.29 ms | 0.0086 ms |
| Forty label updates on one 8 MiB GUI image | 320 MiB copied | No image bytes copied |
| Transfer an 8 MiB binary payload between JS contexts | 2.406 ms | 0.0359 ms |
| GUI ordering: 100 containers, 20 controls each, 500 order updates | 88.0 ms | 42.9 ms |
| Container snapshots invalidated by that ordering workload | 50,000 | 499 |
| Plotly string preflight, one million ASCII characters | 88.48 ms | 3.47 ms |
| Plotly string preflight, one million supplementary Unicode characters | 123.35 ms | 12.59 ms |
| Normalize a 1080p RGB float32 image: peak traced temporary allocation | 47.46 MiB | 29.66 MiB |

Transport comparisons load the baseline and modified implementations into
the same Python process; enqueue numbers are medians of two runs.
Client preflight/transfer figures are medians of 25 runs; ordering figures
are medians of five warmed runs, excluding setup. Text figures use the best
of three runs. Image memory uses tracemalloc with the source already allocated.
These measurements isolate the changed operations; their speedups should not
be multiplied together or interpreted as total application speedups.

## Implemented changes

### Server transport and HTTP

[AsyncMessageBuffer](src/leika/infra/_async_message_buffer.py) now indexes
lifecycle entities and removal tombstones. Ordinary insertion and successful
send acknowledgement no longer scan the entire retained scene. Entity removal
looks up the affected messages directly.

A sorted message-ID index lets replay seek past delivered history and lets
connection-local drains skip gaps left by coalesced updates. Stale IDs are
compacted, keeping bookkeeping bounded by retained state. Transaction rollback,
lifecycle removal, completion, and client cursors include the new indexes.
This exchanges some per-message bookkeeping memory for much less repeated CPU
work; it does not retain additional visualization payloads.

[Static HTTP caching](src/leika/infra/_http_server.py) keeps both valid gzip
and identity representations. Previously, requesting one evicted the other.
Eight alternating accesses now require two file reads and one compression,
instead of eight reads and four compressions. File-generation changes still
invalidate old representations, and the existing cache byte limits still apply.

[Metadata preflight](src/leika/infra/_infra.py) uses an ASCII fast path and
bounded native UTF-8 conversions instead of a Python loop over every character.

### Browser data flow and responsiveness

[Hybrid decoding](src/leika/client/src/hybridMessageDecode.ts) hands off both
owned backing buffers: the raw frame and decompressed msgpack metadata.
Previously, transferring only the raw frame left binary values inside metadata
to be copied by structured clone. The installed zstd decoder returns an
independent buffer, so transfer does not detach its reusable WASM memory.

[Uploads](src/leika/client/src/fileUpload.ts) also transfer ownership of each
freshly read file chunk to the worker. Ordinary GUI event data retains its
existing ownership behavior.

[Queue processing](src/leika/client/src/messageQueueProcessor.ts) yields after
approximately 8 ms between complete wire frames. An advancing queue head avoids
repeated array shifts, and pending frames retain their memory reservations.
Scheduling stops when the queue is empty. Message order, complete-frame
validation, and connection-failure behavior remain intact.

[GUI preflight](src/leika/client/src/ControlPanel/GuiState.ts) reuses graph
validation within a frame until a lifecycle message changes ownership.
GUI, viewport, and notification validators skip frames containing no messages
that can affect their state.

GUI and viewport image states preserve their owned binary reference when only
display properties change. This avoids another image-sized copy and prevents
image hooks from recreating URLs and decoding unchanged content. New incoming
image buffers still receive independent retained snapshots. Viewport property
updates with no changed values also avoid publishing another state.

### Rendering and observers

[Generated controls](src/leika/client/src/ControlPanel/Generated.tsx) use stable
context values and memoized inputs. Each container's
[ordering selector](src/leika/client/src/ControlPanel/guiContainerOrder.ts)
preserves its result when another container changes or a rank update leaves
the displayed order unchanged. Equal ranks retain insertion order.

Folder/popout headers subscribe to whether their container is empty, rather
than its complete membership map.

[Size observation](src/leika/client/src/hooks/elementSizeObserver.ts) shares one
ResizeObserver across plot hosts and consumes the browser's measured border
boxes. It retains an initial geometry read and a fallback for unavailable
measurements. A 1,000-delivery test now performs one initial geometry read,
instead of 1,001.

[Theme subscriptions](src/leika/client/src/hooks/colorSchemeStore.ts) share one
MutationObserver. Irrelevant root class changes do not notify consumers.
Both shared observers release their native observer when the last subscriber
leaves, and ignore late deliveries from retired instances.

### Python preparation and startup

[Text validation](src/leika/_validation.py) uses native scans/conversions and
constant-time ASCII/length checks where possible. Unicode conversions process
at most 64 Ki-characters at once, avoiding an unbounded encoded temporary.
Supplementary characters, surrogates, and chunk boundaries have regression
coverage.

[Plotly string bounds](src/leika/_plotly.py) use native escaping in bounded
chunks. Conservative control-character charges and size rejection remain.
The new preflight also counts DEL's JSON escape correctly.

[Float image normalization](src/leika/_assignable_props_api.py) scales the
private clipped array in place, eliminating a full floating-point intermediate
without modifying the caller's image or changing clipping/rounding behavior.

The [compressed HTML loader](src/leika/client/vite-plugin-compress-html.mts)
installs CSS as soon as it finishes decompressing and removes temporary loader
and application-script elements after use. Startup failures remain visible.

## Startup footprint and remaining costs

The baseline already used a compressed single-file client, page-scoped pane
delivery, lazy Plotly runtime delivery, keyed control subscriptions, paced
uploads, and bounded caches. Those mechanisms were retained.

The generated HTML changed from 756,504 to 757,997 bytes, an increase of about
0.2%. HTTP gzip at level 6 changed from 571,876 to 572,977 bytes. The small
increase contains the scheduling/indexing helpers; this work improves runtime
efficiency rather than materially shrinking the download.

The following limits remain relevant:

- One large wire frame must finish validation/application before yielding.
  The 8 ms target is not a hard upper bound on individual main-thread tasks.
- Large Plotly figures, Markdown documents, image encoding/decoding, and browser
  DOM layout still incur work proportional to their content.
- Downloads still assemble a complete Blob within the existing document budget.
- No end-to-end cold-load or remote-network speedup is claimed from these
  microbenchmarks.

## Verification

All completed successfully:

- 985 Python tests, up from 953 at baseline.
- 1,150 client unit tests across 106 files, up from 1,125 tests at baseline.
- All 209 Chromium integration tests against the generated production client.
- Python Ruff lint/format and Pyright; client TypeScript, ESLint, and Prettier.
- Generated protocol/version consistency, documentation checks, and whitespace
  checks.
- Canonical production client build via leika-build-client --force.

Regression tests cover rollback and index cleanup, sparse queues and replay,
HTTP representation reuse, transferable ownership, pending-queue accounting,
GUI lifecycle validation, image identity, observer cleanup, Unicode boundaries,
image normalization, and compressed-loader success/failure.

The local build is refreshed. No release, deployment, or dependency update
was made.
