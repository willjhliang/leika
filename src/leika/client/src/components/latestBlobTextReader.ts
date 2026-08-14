/**
 * Serialize Blob-to-string decoding while retaining only the newest request.
 *
 * `Blob.text()` cannot be cancelled once a browser has started it. A rapid
 * series of preview reloads must therefore not start a conversion for every
 * Blob: each conversion can transiently hold both the Blob and its decoded
 * string. This reader permits one unavoidable active conversion and keeps at
 * most one not-yet-read replacement. A newer request drops the callback and
 * Blob reference belonging to every older pending request.
 */

type TextResult = (text: string) => void;

interface ReadRequest {
  blob: Blob;
  result: TextResult | null;
}

export class LatestBlobTextReader {
  private active: ReadRequest | null = null;
  private pending: ReadRequest | null = null;

  /** Read `blob` when no older conversion is still running.
   *
   * The returned function forgets this request. It cannot stop an active
   * browser conversion, but it does release the component callback and stops
   * that conversion from publishing stale text.
   */
  request(blob: Blob, result: TextResult): () => void {
    // React development Strict Mode deliberately repeats an effect's
    // setup/cleanup. Reattach to the same unavoidable browser conversion
    // instead of decoding the same Blob a second time after the rehearsal.
    if (this.active?.blob === blob) {
      const active = this.active;
      active.result = result;
      if (this.pending !== null) this.pending.result = null;
      this.pending = null;
      return () => {
        if (active.result === result) active.result = null;
      };
    }
    const request: ReadRequest = { blob, result };
    if (this.active === null) {
      this.start(request);
    } else {
      // A request means the previous result is no longer current, even when a
      // caller has not yet run the cleanup returned for it.
      this.active.result = null;
      if (this.pending !== null) this.pending.result = null;
      this.pending = request;
    }
    return () => {
      request.result = null;
      if (this.pending === request) this.pending = null;
    };
  }

  /** Forget every result and every Blob that has not started decoding. */
  clear(): void {
    if (this.active !== null) this.active.result = null;
    if (this.pending !== null) this.pending.result = null;
    this.pending = null;
  }

  private start(request: ReadRequest): void {
    this.active = request;
    let decoded: Promise<string>;
    try {
      decoded = request.blob.text();
    } catch {
      this.finish(request, "");
      return;
    }
    void decoded.then(
      (text) => this.finish(request, text),
      () => this.finish(request, ""),
    );
  }

  private finish(request: ReadRequest, text: string): void {
    const result = request.result;
    request.result = null;
    try {
      result?.(text);
    } finally {
      if (this.active === request) this.active = null;
      const next = this.pending;
      this.pending = null;
      if (next !== null && next.result !== null) this.start(next);
    }
  }
}
