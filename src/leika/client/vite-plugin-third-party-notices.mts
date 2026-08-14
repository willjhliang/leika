import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import type { Plugin } from "vite";

export const THIRD_PARTY_NOTICES_FILE = "THIRD_PARTY_NOTICES.txt";

const CLIENT_DIR = fileURLToPath(new URL(".", import.meta.url));
const OVERRIDE_DIR = path.join(CLIENT_DIR, "third-party-license-overrides");
const LICENSE_NAME = /^(?:licen[cs]e|copying|notice)(?:$|[._-])/i;

type LicenseOverride = {
  file: string;
  source: string;
};

const LICENSE_OVERRIDES = new Map<string, LicenseOverride>([
  [
    "hast-util-to-string@2.0.0",
    {
      file: path.join(OVERRIDE_DIR, "hast-util-to-string-2.0.0.txt"),
      source:
        "https://github.com/rehypejs/rehype-minify/blob/c4155515a636c62dad5bbcf74ae286e0355405df/license",
    },
  ],
  [
    "react-remove-scroll-bar@2.3.8",
    {
      file: path.join(OVERRIDE_DIR, "react-remove-scroll-bar-2.3.8.txt"),
      source:
        "https://github.com/theKashey/react-remove-scroll-bar/blob/8ca9ba5ea52de03308fe8ced94f7b159a44d28ff/LICENSE",
    },
  ],
]);

type PackageManifest = {
  name?: unknown;
  version?: unknown;
  license?: unknown;
  repository?: unknown;
};

type LicenseDocument = {
  name: string;
  source?: string;
  text: string;
};

type PackageNotice = {
  declaredLicense: string;
  documents: LicenseDocument[];
  key: string;
  repository?: string;
};

function packageNameFromSpecifier(specifier: string): string {
  const parts = specifier.split("/");
  return specifier.startsWith("@") ? parts.slice(0, 2).join("/") : parts[0];
}

function findInstalledPackage(packageName: string, fromFile: string): string {
  let directory = path.dirname(path.resolve(fromFile));
  const packageParts = packageName.split("/");
  while (true) {
    const candidate = path.join(directory, "node_modules", ...packageParts);
    if (fs.existsSync(path.join(candidate, "package.json"))) return candidate;
    const parent = path.dirname(directory);
    if (parent === directory) {
      throw new Error(
        "Cannot resolve package " + packageName + " required by " + fromFile,
      );
    }
    directory = parent;
  }
}

export function packageRootForModule(moduleId: string): string | null {
  const clean = moduleId
    .replaceAll("\\", "/")
    .replaceAll("\0", "")
    .split("?", 1)[0];
  const marker = "/node_modules/";
  const markerIndex = clean.lastIndexOf(marker);
  if (markerIndex < 0) return null;

  const prefix = clean.slice(0, markerIndex + marker.length);
  const parts = clean.slice(markerIndex + marker.length).split("/");
  const packageParts = parts[0]?.startsWith("@")
    ? parts.slice(0, 2)
    : parts.slice(0, 1);
  if (
    packageParts.length === 0 ||
    packageParts.some((part) => part.length === 0)
  ) {
    return null;
  }
  const root = path.normalize(prefix + packageParts.join("/"));
  return fs.existsSync(path.join(root, "package.json")) ? root : null;
}

export function packageRootsForCssImports(cssEntry: string): string[] {
  const source = fs.readFileSync(cssEntry, "utf8");
  const roots = new Set<string>();
  const imports = source.matchAll(
    /@import\s+(?:"([^"]+)"|'([^']+)'|url\(\s*(?:"([^"]+)"|'([^']+)'|([^"'()\s]+))\s*\))/gi,
  );
  for (const match of imports) {
    const specifier = match.slice(1).find((value) => value !== undefined);
    if (
      specifier === undefined ||
      specifier.startsWith(".") ||
      specifier.startsWith("/") ||
      /^[a-z][a-z0-9+.-]*:/i.test(specifier)
    ) {
      continue;
    }
    roots.add(
      findInstalledPackage(packageNameFromSpecifier(specifier), cssEntry),
    );
  }
  return [...roots].sort();
}

export function packageRootsForBundlerRuntime(referenceFile: string): string[] {
  // Vite's modulepreload polyfill, Rollup's CommonJS interop helpers, and
  // esbuild's transformed TypeScript helpers can be generated code with no
  // node_modules path for moduleParsed(). Include all three generators
  // conservatively; their license files carry attribution for embedded code.
  return ["esbuild", "rollup", "vite"]
    .map((packageName) => findInstalledPackage(packageName, referenceFile))
    .sort();
}
function compareText(left: string, right: string): number {
  return left < right ? -1 : left > right ? 1 : 0;
}

function repositoryUrl(value: unknown): string | undefined {
  if (typeof value === "string") return value;
  if (typeof value !== "object" || value === null || !("url" in value))
    return undefined;
  return typeof value.url === "string" ? value.url : undefined;
}

function licenseDocuments(root: string, key: string): LicenseDocument[] {
  const documents = fs
    .readdirSync(root, { withFileTypes: true })
    .filter((entry) => entry.isFile() && LICENSE_NAME.test(entry.name))
    .sort((left, right) => compareText(left.name, right.name))
    .map((entry) => ({
      name: entry.name,
      text: fs.readFileSync(path.join(root, entry.name), "utf8").trimEnd(),
    }));
  if (documents.length > 0) return documents;

  const override = LICENSE_OVERRIDES.get(key);
  if (override === undefined) {
    throw new Error(
      "Bundled package " +
        key +
        " has no top-level license file; add an exact-version reviewed override",
    );
  }
  return [
    {
      name: path.basename(override.file),
      source: override.source,
      text: fs.readFileSync(override.file, "utf8").trimEnd(),
    },
  ];
}

function readPackageNotice(root: string): PackageNotice {
  const manifest = JSON.parse(
    fs.readFileSync(path.join(root, "package.json"), "utf8"),
  ) as PackageManifest;
  if (
    typeof manifest.name !== "string" ||
    typeof manifest.version !== "string"
  ) {
    throw new Error(
      "Bundled package manifest lacks a string name/version: " + root,
    );
  }
  if (typeof manifest.license !== "string") {
    throw new Error(
      "Bundled package " +
        manifest.name +
        "@" +
        manifest.version +
        " lacks a license identifier",
    );
  }

  const key = manifest.name + "@" + manifest.version;
  return {
    declaredLicense: manifest.license,
    documents: licenseDocuments(root, key),
    key,
    repository: repositoryUrl(manifest.repository),
  };
}

export function renderThirdPartyNotices(
  packageRoots: Iterable<string>,
): string {
  const packages = new Map<string, PackageNotice>();
  for (const root of packageRoots) {
    const notice = readPackageNotice(root);
    const previous = packages.get(notice.key);
    if (previous !== undefined) {
      if (JSON.stringify(previous) !== JSON.stringify(notice)) {
        throw new Error("Conflicting bundled copies of " + notice.key);
      }
      continue;
    }
    packages.set(notice.key, notice);
  }

  const lines = [
    "LEIKA BROWSER CLIENT THIRD-PARTY NOTICES",
    "",
    "Generated from the production module graph, direct CSS imports, and",
    "the Vite/Rollup/esbuild generators of virtual runtime helper modules.",
    "Do not edit this file; update dependencies or reviewed license overrides instead.",
  ];
  for (const notice of [...packages.values()].sort((left, right) =>
    compareText(left.key, right.key),
  )) {
    lines.push("", "=".repeat(80), notice.key);
    lines.push("Declared license: " + notice.declaredLicense);
    if (notice.repository !== undefined)
      lines.push("Repository: " + notice.repository);
    for (const document of notice.documents) {
      lines.push("", "-".repeat(80), "License document: " + document.name);
      if (document.source !== undefined)
        lines.push("Source: " + document.source);
      lines.push("-".repeat(80), document.text);
    }
  }
  lines.push("");
  return lines.join("\n");
}

function noticePlugin(packageRoots: Set<string>, emit: boolean): Plugin {
  return {
    name: emit
      ? "leika-third-party-notices"
      : "leika-worker-third-party-notices",
    apply: "build",
    moduleParsed(info) {
      const root = packageRootForModule(info.id);
      if (root !== null) packageRoots.add(root);
    },
    generateBundle() {
      if (!emit) return;
      this.emitFile({
        type: "asset",
        fileName: THIRD_PARTY_NOTICES_FILE,
        source: renderThirdPartyNotices(packageRoots),
      });
    },
  };
}

export function createThirdPartyNotices(
  cssEntry = path.join(CLIENT_DIR, "src", "index.css"),
): { plugin: Plugin; workerPlugins: () => Plugin[] } {
  const packageRoots = new Set([
    ...packageRootsForCssImports(cssEntry),
    ...packageRootsForBundlerRuntime(cssEntry),
  ]);
  return {
    plugin: noticePlugin(packageRoots, true),
    workerPlugins: () => [noticePlugin(packageRoots, false)],
  };
}
