import { fileURLToPath, URL } from "node:url";

import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

import browserslistToEsbuild from "browserslist-to-esbuild";
import { viteSingleFile } from "vite-plugin-singlefile";
import { createThirdPartyNotices } from "./vite-plugin-third-party-notices.mts";

export default defineConfig(({ command }) => {
  const isDev = command === "serve";
  const notices = createThirdPartyNotices();

  return {
    plugins: [
      tailwindcss(),
      react(),
      ...(!isDev ? [viteSingleFile(), notices.plugin] : []),
    ],
    resolve: {
      alias: {
        "@": fileURLToPath(new URL("./src", import.meta.url)),
        // The browser export uses document.createElement, unavailable in a
        // Markdown worker. The default export is the equivalent entity table.
        "decode-named-character-reference": fileURLToPath(
          import.meta.resolve("decode-named-character-reference"),
        ),
      },
    },
    server: {
      port: 3000,
      hmr: { port: 1025 },
    },
    build: {
      outDir: "build",
      target: browserslistToEsbuild(),
      assetsInlineLimit: 100000000,
      rollupOptions: {
        output: {
          inlineDynamicImports: true,
        },
      },
    },
    worker: {
      format: "es",
      plugins: notices.workerPlugins,
      rollupOptions: {
        output: {
          inlineDynamicImports: true,
        },
      },
    },
  };
});
