import { fileURLToPath, URL } from "node:url";

import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

import browserslistToEsbuild from "browserslist-to-esbuild";
import { viteSingleFile } from "vite-plugin-singlefile";
import { compressHtml } from "./vite-plugin-compress-html.mts";
import { createThirdPartyNotices } from "./vite-plugin-third-party-notices.mts";

export default defineConfig(({ command }) => {
  const isDev = command === "serve";
  const notices = createThirdPartyNotices();

  return {
    plugins: [
      tailwindcss(),
      react(),
      ...(!isDev ? [viteSingleFile(), compressHtml()] : []),
      ...(!isDev ? [notices.plugin] : []),
    ],
    resolve: {
      alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) },
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
