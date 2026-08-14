import type { Plugin } from "vite";
import { gzipSync } from "node:zlib";

// Base64 encoding that's safe for embedding in HTML.
function toBase64(buffer: Buffer): string {
  return buffer.toString("base64");
}

const INLINE_STYLE = /<style\b[^>]*>([\s\S]*?)<\/style>/i;
const INLINE_MODULE_SCRIPT =
  /<script\b(?=[^>]*\btype\s*=\s*(?:"module"|'module'))(?![^>]*\bsrc\s*=)[^>]*>([\s\S]*?)<\/script>/i;

type CompressedPayload = {
  html: string;
  attribute: string;
};

function takeAndCompress(
  html: string,
  pattern: RegExp,
  attribute: "s" | "c",
): CompressedPayload | null {
  const match = pattern.exec(html);
  if (match === null || match.index === undefined) return null;

  const source = Buffer.from(match[1], "utf8");
  const compressed = gzipSync(source, { level: 9 });
  return {
    html:
      html.slice(0, match.index) + html.slice(match.index + match[0].length),
    attribute: ` data-${attribute}="${toBase64(compressed)}"`,
  };
}

// A browser-native gzip loader keeps the build independent of zstddec's
// private generated-source layout. DecompressionStream was already required
// by the previous loader to unpack its WASM decoder, so this does not widen
// the supported-browser requirement.
function makeLoaderScript(): string {
  return `
(async()=>{
  if(typeof DecompressionStream!=="function")throw new Error("DecompressionStream is unavailable");
  const d=document.currentScript.dataset;
  const dec=async(b64)=>{
    const b=atob(b64);const a=new Uint8Array(b.length);for(let i=0;i<b.length;i++)a[i]=b.charCodeAt(i);
    const stream=new Blob([a]).stream().pipeThrough(new DecompressionStream("gzip"));
    return new Response(stream).text();
  };
  const [css,code]=await Promise.all([d.s?dec(d.s):null,d.c?dec(d.c):null]);
  if(css!==null){const e=document.createElement("style");e.textContent=css;document.head.appendChild(e);}
  if(code!==null){
    await new Promise((resolve,reject)=>{
      const run=()=>{
        const e=document.createElement("script");e.type="module";e.textContent=code;
        e.addEventListener("load",resolve,{once:true});
        e.addEventListener("error",()=>reject(new Error("Application module failed to load")),{once:true});
        document.head.appendChild(e);
      };
      if(document.readyState==="loading"){document.addEventListener("DOMContentLoaded",run,{once:true});}else{run();}
    });
  }
})().catch(error=>{
  const show=()=>{
    const status=document.createElement("pre");status.setAttribute("role","alert");
    status.textContent="Leika could not start. Reload the page or use a supported browser.";
    (document.body||document.documentElement).replaceChildren(status);
  };
  if(document.body)show();else document.addEventListener("DOMContentLoaded",show,{once:true});
  console.error("Leika startup failed:",error);
});
`
    .trim()
    .replace(/\n/g, "");
}

/** Compress the single-file plugin's inline payloads into one loader tag. */
export function compressInlineHtml(source: string): string {
  const style = takeAndCompress(source, INLINE_STYLE, "s");
  const script = takeAndCompress(
    style?.html ?? source,
    INLINE_MODULE_SCRIPT,
    "c",
  );
  if (script === null) {
    throw new Error(
      "Expected an inline module script in the single-file HTML build",
    );
  }

  const headClose = script.html.lastIndexOf("</head>");
  if (headClose < 0) throw new Error("Expected </head> in the HTML build");

  const loaderTag = `<script${style?.attribute ?? ""}${script.attribute}>${makeLoaderScript()}</script>`;
  return (
    script.html.slice(0, headClose) + loaderTag + script.html.slice(headClose)
  );
}

export function compressHtml(): Plugin {
  return {
    name: "compress-html",
    enforce: "post",
    generateBundle(_, bundle) {
      for (const [fileName, chunk] of Object.entries(bundle)) {
        if (!fileName.endsWith(".html") || chunk.type !== "asset") continue;

        const source =
          typeof chunk.source === "string"
            ? chunk.source
            : Buffer.from(chunk.source).toString("utf8");
        const originalSize = Buffer.byteLength(source, "utf8");
        const html = compressInlineHtml(source);
        const newSize = Buffer.byteLength(html, "utf8");
        console.log(
          `[compress-html] ${fileName}: ${(originalSize / 1024).toFixed(1)} KiB -> ${(newSize / 1024).toFixed(1)} KiB`,
        );
        chunk.source = html;
      }
    },
  };
}
