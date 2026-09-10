import { runInNewContext } from "node:vm";
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
    expect(output).toContain('typeof DecompressionStream!=="function"');
    expect(output).toContain(".catch(error=>");
    expect(output).toContain('setAttribute("role","alert")');
    expect(output).toContain("Leika could not start.");
    expect(output).toContain("DOMContentLoaded");
    expect(output).toContain('addEventListener("error"');
    expect(output).toContain("Application module failed to load");
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

type LoaderElement = {
  tagName: string;
  textContent: string;
  type: string;
  removed: boolean;
  listeners: Map<string, () => void>;
  addEventListener: (event: string, listener: () => void) => void;
  remove: () => void;
  setAttribute: (name: string, value: string) => void;
};

async function runLoader(html: string, moduleFails = false) {
  const match = /<script( data-[^>]+)>([\s\S]*?)<\/script>/.exec(html);
  if (match === null) throw new Error("Missing loader script");
  const dataset = Object.fromEntries(
    [...match[1].matchAll(/data-([sc])="([^"]+)"/g)].map((entry) => [
      entry[1],
      entry[2],
    ]),
  );
  const appended: LoaderElement[] = [];
  let loaderRemoved = false;
  let alert: LoaderElement | undefined;
  const errors: unknown[] = [];
  const document = {
    currentScript: {
      dataset,
      remove: () => {
        loaderRemoved = true;
      },
    },
    readyState: "complete",
    createElement: (tagName: string): LoaderElement => {
      const element: LoaderElement = {
        tagName,
        textContent: "",
        type: "",
        removed: false,
        listeners: new Map(),
        addEventListener(event, listener) {
          this.listeners.set(event, listener);
        },
        remove() {
          this.removed = true;
        },
        setAttribute() {},
      };
      return element;
    },
    head: {
      appendChild: (element: LoaderElement) => {
        appended.push(element);
        if (element.tagName === "script") {
          element.listeners.get(moduleFails ? "error" : "load")?.();
        }
      },
    },
    body: {
      replaceChildren: (element: LoaderElement) => {
        alert = element;
      },
    },
  };
  await runInNewContext(match[2], {
    document,
    Blob,
    Response,
    DecompressionStream,
    atob,
    console: { error: (...args: unknown[]) => errors.push(args) },
  });
  return { appended, loaderRemoved, alert, errors };
}

describe("compressed startup execution", () => {
  const css = "body { color: red; }";
  const code = "globalThis.started = true;";
  const html = () =>
    compressInlineHtml(
      "<html><head><style>" +
        css +
        '</style><script type="module">' +
        code +
        "</script></head><body></body></html>",
    );

  it("decompresses the real payloads and releases both temporary script tags", async () => {
    const result = await runLoader(html());
    expect(result.loaderRemoved).toBe(true);
    const style = result.appended.find(
      (element) => element.tagName === "style",
    );
    const script = result.appended.find(
      (element) => element.tagName === "script",
    );
    expect(style?.textContent).toBe(css);
    expect(style?.removed).toBe(false);
    expect(script?.textContent).toBe(code);
    expect(script?.type).toBe("module");
    expect(script?.removed).toBe(true);
    expect(result.errors).toEqual([]);
    expect(result.alert).toBeUndefined();
  });

  it("still displays a startup failure and releases a failed module", async () => {
    const result = await runLoader(html(), true);
    expect(result.alert?.textContent).toContain("Leika could not start.");
    expect(result.errors).toHaveLength(1);
    expect(
      result.appended.find((element) => element.tagName === "script")?.removed,
    ).toBe(true);
  });

  it("reports corrupt compressed data without installing an application script", async () => {
    const result = await runLoader(
      html().replace(/data-c="[^"]+"/, 'data-c="AAAA"'),
    );
    expect(result.alert?.textContent).toContain("Leika could not start.");
    expect(
      result.appended.some((element) => element.tagName === "script"),
    ).toBe(false);
  });
});
