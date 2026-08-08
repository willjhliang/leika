import { gunzipSync } from "node:zlib";

import { describe, expect, it } from "vitest";

import { compressInlineHtml } from "../vite-plugin-compress-html.mts";

function decompressedAttribute(html: string, name: "s" | "c"): string {
  const match = new RegExp(`data-${name}="([^"]+)"`).exec(html);
  if (match === null) throw new Error(`Missing data-${name} payload`);
  return gunzipSync(Buffer.from(match[1], "base64")).toString("utf8");
}

describe("compressInlineHtml", () => {
  it("compresses inline CSS and JavaScript without a bundled decoder", () => {
    const style = "body { color: rebeccapurple; }";
    const script = 'document.querySelector("#root");';
    const output = compressInlineHtml(`<!doctype html><html><head>
      <style data-vite>${style}</style>
      <script crossorigin type='module'>${script}</script>
      </head><body><div id="root"></div></body></html>`);

    expect(decompressedAttribute(output, "s")).toBe(style);
    expect(decompressedAttribute(output, "c")).toBe(script);
    expect(output).not.toContain("<style data-vite>");
    expect(output).not.toContain("<script crossorigin type='module'>");
    expect(output).toContain('new DecompressionStream("gzip")');
    expect(output).not.toContain("WebAssembly");
  });

  it("allows a build with no stylesheet", () => {
    const output = compressInlineHtml(
      '<html><head><script type="module">start()</script></head></html>',
    );

    expect(output).not.toContain("data-s=");
    expect(decompressedAttribute(output, "c")).toBe("start()");
  });

  it("fails loudly if the single-file plugin stops inlining JavaScript", () => {
    expect(() =>
      compressInlineHtml(
        '<html><head><script type="module" src="app.js"></script></head></html>',
      ),
    ).toThrow(/inline module script/);
  });

  it("fails loudly when the document has no head boundary", () => {
    expect(() =>
      compressInlineHtml('<script type="module">start()</script>'),
    ).toThrow(/<\/head>/);
  });
});
