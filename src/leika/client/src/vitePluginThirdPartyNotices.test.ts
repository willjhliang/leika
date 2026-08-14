import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { build } from "vite";
import { afterEach, describe, expect, it } from "vitest";

import {
  createThirdPartyNotices,
  packageRootForModule,
  packageRootsForBundlerRuntime,
  packageRootsForCssImports,
  renderThirdPartyNotices,
} from "../vite-plugin-third-party-notices.mts";

const temporaryDirectories: string[] = [];

function temporaryDirectory(): string {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), "leika-notices-"));
  temporaryDirectories.push(directory);
  return directory;
}

function packageFixture(
  parent: string,
  name: string,
  version: string,
  licenseText?: string,
): string {
  const root = path.join(parent, "node_modules", ...name.split("/"));
  fs.mkdirSync(root, { recursive: true });
  fs.writeFileSync(
    path.join(root, "package.json"),
    JSON.stringify({
      name,
      version,
      license: "MIT",
      repository: { url: "https://example.test/" + name },
    }),
  );
  fs.writeFileSync(path.join(root, "index.js"), "export default true;\n");
  if (licenseText !== undefined) {
    fs.writeFileSync(path.join(root, "LICENSE"), licenseText);
  }
  return root;
}

afterEach(() => {
  for (const directory of temporaryDirectories.splice(0)) {
    fs.rmSync(directory, { recursive: true, force: true });
  }
});

describe("third-party notices", () => {
  it("combines CSS, bundler, main, and worker production roots", async () => {
    const directory = temporaryDirectory();
    const css = path.join(directory, "src", "index.css");
    fs.mkdirSync(path.dirname(css), { recursive: true });
    fs.writeFileSync(css, '@import "css-runtime";\n');
    packageFixture(directory, "css-runtime", "1.0.0", "css license");
    packageFixture(directory, "esbuild", "1.0.0", "esbuild license");
    packageFixture(directory, "rollup", "1.0.0", "rollup license");
    packageFixture(directory, "vite", "1.0.0", "vite license");
    packageFixture(directory, "main-runtime", "1.0.0", "main license");
    packageFixture(directory, "worker-runtime", "1.0.0", "worker license");
    fs.writeFileSync(
      path.join(directory, "index.html"),
      '<script type="module" src="/main.js"></script>\n',
    );
    fs.writeFileSync(
      path.join(directory, "main.js"),
      [
        'import value from "main-runtime";',
        'new Worker(new URL("./worker.js", import.meta.url), { type: "module" });',
        "console.log(value);",
      ].join("\n"),
    );
    fs.writeFileSync(
      path.join(directory, "worker.js"),
      'import value from "worker-runtime"; console.log(value);\n',
    );
    const notices = createThirdPartyNotices(css);
    const output = path.join(directory, "build");

    await build({
      build: { outDir: output },
      configFile: false,
      logLevel: "silent",
      plugins: [notices.plugin],
      root: directory,
      worker: { format: "es", plugins: notices.workerPlugins },
    });
    const source = fs.readFileSync(
      path.join(output, "THIRD_PARTY_NOTICES.txt"),
      "utf8",
    );

    for (const packageKey of [
      "css-runtime@1.0.0",
      "esbuild@1.0.0",
      "main-runtime@1.0.0",
      "rollup@1.0.0",
      "vite@1.0.0",
      "worker-runtime@1.0.0",
    ]) {
      expect(source).toContain(packageKey);
    }
  });

  it("resolves scoped, nested, queried, and Windows-style module identifiers", () => {
    const directory = temporaryDirectory();
    const root = packageFixture(
      directory,
      "@scope/example",
      "1.0.0",
      "full text",
    );
    const nested = packageFixture(
      path.join(directory, "node_modules", "parent"),
      "@nested/example",
      "2.0.0",
      "nested full text",
    );

    expect(
      packageRootForModule(
        path.join(root, "dist", "index.js") + "?commonjs-entry",
      ),
    ).toBe(root);
    expect(
      packageRootForModule(path.join(nested, "index.js").replaceAll("/", "\\")),
    ).toBe(nested);
    expect(
      packageRootForModule(path.join(directory, "src", "index.ts")),
    ).toBeNull();
  });

  it("attributes virtual runtime helpers to their bundler generators", () => {
    const directory = temporaryDirectory();
    const reference = path.join(directory, "src", "index.css");
    const esbuild = packageFixture(
      directory,
      "esbuild",
      "0.28.1",
      "esbuild license",
    );
    const vite = packageFixture(directory, "vite", "7.0.0", "vite license");
    const rollup = packageFixture(
      directory,
      "rollup",
      "4.0.0",
      "rollup license",
    );

    expect(packageRootsForBundlerRuntime(reference)).toEqual(
      [esbuild, rollup, vite].sort(),
    );
  });

  it("discovers every bare CSS import without treating local files as packages", () => {
    const directory = temporaryDirectory();
    const css = path.join(directory, "src", "index.css");
    fs.mkdirSync(path.dirname(css), { recursive: true });
    const alpha = packageFixture(directory, "alpha", "1.0.0", "alpha license");
    const beta = packageFixture(
      directory,
      "@scope/beta",
      "2.0.0",
      "beta license",
    );
    fs.writeFileSync(
      css,
      [
        '@import "alpha";',
        "@import url('@scope/beta/theme.css') layer(theme);",
        "@import url(alpha/print.css) print;",
        '@import url("./local.css");',
        '@import url("https://example.test/external.css");',
      ].join("\n"),
    );

    expect(packageRootsForCssImports(css)).toEqual([beta, alpha].sort());
  });

  it("preserves complete license documents and deterministic package order", () => {
    const directory = temporaryDirectory();
    const zeta = packageFixture(
      directory,
      "zeta",
      "1.0.0",
      "zeta full license",
    );
    const alpha = packageFixture(
      directory,
      "alpha",
      "2.0.0",
      "alpha full license",
    );

    const notices = renderThirdPartyNotices([zeta, alpha, alpha]);

    expect(notices).toContain(
      "the Vite/Rollup/esbuild generators of virtual runtime helper modules.",
    );
    expect(notices.indexOf("alpha@2.0.0")).toBeLessThan(
      notices.indexOf("zeta@1.0.0"),
    );
    expect(notices.match(/^alpha@2\.0\.0$/gm)).toHaveLength(1);
    expect(notices).toContain("alpha full license");
    expect(notices).toContain("zeta full license");
  });

  it("rejects a bundled package without a full license document", () => {
    const directory = temporaryDirectory();
    const root = packageFixture(directory, "missing-license", "1.0.0");

    expect(() => renderThirdPartyNotices([root])).toThrow(
      "has no top-level license file",
    );
  });

  it("uses reviewed exact-version overrides for npm tarballs that omit licenses", () => {
    const client = fileURLToPath(new URL("..", import.meta.url));
    const notices = renderThirdPartyNotices([
      path.join(client, "node_modules", "hast-util-to-string"),
      path.join(client, "node_modules", "react-remove-scroll-bar"),
    ]);

    expect(notices).toContain("hast-util-to-string@2.0.0");
    expect(notices).toContain("Copyright (c) 2016 Titus Wormer");
    expect(notices).toContain("react-remove-scroll-bar@2.3.8");
    expect(notices).toContain("Copyright (c) 2025 Anton Korzunov");
  });
});
