import { isAbsolute, posix, relative, resolve, win32 } from "node:path";

import { build as viteBuild, type Plugin } from "vite";

import { renderWidgetBundle, type BuildArtifact } from "./bundle.js";
import { buildVirtualEntry } from "./html.js";
import { hasDefaultExport } from "./validate-widget.js";

const MAX_INLINE_ASSET_SIZE = Number.MAX_SAFE_INTEGER;
const VIRTUAL_DIRECTORY = ".belgie-virtual-widget";
const WIDGET_FILE = "widget.tsx";
const ENTRY_FILE = "__entry.tsx";
const DEFAULT_DEPENDENCIES = ["@belgie/mcp", "react", "react-dom"];
const INTERNAL_DEPENDENCIES = ["vite", "rolldown", "lightningcss"];
const MODULE_EXTENSIONS = ["", ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".css", ".json"];
const INDEX_EXTENSIONS = MODULE_EXTENSIONS.slice(1).map((extension) => `/index${extension}`);
const TEXT_ASSET_TYPES = new Map([
  [".html", "text/html"],
  [".md", "text/markdown"],
  [".svg", "image/svg+xml"],
  [".txt", "text/plain"],
]);

export type BuildWidgetOptions = {
  dependencies?: string[];
  files?: Record<string, string>;
  root: string;
  widget: string;
};

export type BuiltWidget = {
  html: string;
};

type BuildOutput = {
  output: BuildArtifact[];
};

type ViteBuild = typeof import("vite").build;

function normalizePath(value: string): string {
  return value.replaceAll("\\", "/");
}

function splitQuery(value: string): [string, string] {
  const index = value.indexOf("?");
  return index === -1 ? [value, ""] : [value.slice(0, index), value.slice(index)];
}

function isWithin(parent: string, child: string): boolean {
  const path = relative(parent, child);
  return path === "" || (!path.startsWith("..") && !isAbsolute(path));
}

function isBareImport(value: string): boolean {
  return !value.startsWith(".") && !value.startsWith("/");
}

function packageAllowed(specifier: string, dependencies: Set<string>): boolean {
  for (const dependency of dependencies) {
    if (specifier === dependency || specifier.startsWith(`${dependency}/`)) {
      return true;
    }
  }
  return false;
}

function packageInternal(specifier: string): boolean {
  if (specifier.startsWith("@belgie/mcp/")) {
    return true;
  }
  return INTERNAL_DEPENDENCIES.some(
    (dependency) => specifier === dependency || specifier.startsWith(`${dependency}/`),
  );
}

function textualAssetModule(fileName: string, source: string, query: string): string | undefined {
  const extension = posix.extname(fileName).toLowerCase();
  const mediaType = TEXT_ASSET_TYPES.get(extension);
  if (mediaType === undefined) {
    return undefined;
  }
  if (query === "?raw") {
    return `export default ${JSON.stringify(source)};\n`;
  }
  const value = `data:${mediaType};charset=utf-8,${encodeURIComponent(source)}`;
  return `export default ${JSON.stringify(value)};\n`;
}

export function validateVirtualPath(fileName: string): void {
  if (
    fileName.length === 0 ||
    fileName.includes("\0") ||
    fileName.includes("\\") ||
    posix.isAbsolute(fileName) ||
    win32.isAbsolute(fileName) ||
    posix.normalize(fileName) !== fileName ||
    fileName === "." ||
    fileName.startsWith("../") ||
    fileName.includes("/../")
  ) {
    throw new Error(`belgie: virtual file path must be a normalized POSIX-relative path: ${JSON.stringify(fileName)}`);
  }
  if (fileName === WIDGET_FILE) {
    throw new Error(`belgie: ${WIDGET_FILE} is supplied through the widget field and cannot appear in files`);
  }
}

function virtualProjectPlugin(
  virtualRoot: string,
  sources: Map<string, string>,
  dependencies: Set<string>,
): Plugin {
  const entryId = normalizePath(resolve(virtualRoot, ENTRY_FILE));
  const widgetId = normalizePath(resolve(virtualRoot, WIDGET_FILE));

  function resolveVirtualImport(source: string, importer: string): string | undefined {
    const [sourcePath, query] = splitQuery(source);
    const importerPath = splitQuery(importer)[0];
    const requested = normalizePath(resolve(importerPath, "..", sourcePath));
    if (!isWithin(virtualRoot, requested)) {
      throw new Error(`belgie: import escapes the virtual project: ${JSON.stringify(source)}`);
    }
    for (const suffix of [...MODULE_EXTENSIONS, ...INDEX_EXTENSIONS]) {
      const candidate = `${requested}${suffix}`;
      if (sources.has(candidate)) {
        return `${candidate}${query}`;
      }
    }
    return undefined;
  }

  return {
    name: "belgie:virtual-widget",
    enforce: "pre",

    async resolveId(source, importer) {
      if (source === entryId) {
        return entryId;
      }
      const [sourcePath, sourceQuery] = splitQuery(source);
      if (sources.has(sourcePath)) {
        return `${sourcePath}${sourceQuery}`;
      }
      if (importer === undefined || !isWithin(virtualRoot, splitQuery(importer)[0])) {
        return null;
      }
      if (/^[a-z][a-z\d+.-]*:/iu.test(source) || source.startsWith("//") || isAbsolute(source) || win32.isAbsolute(source)) {
        throw new Error(`belgie: import scheme or absolute path is not allowed: ${JSON.stringify(source)}`);
      }
      if (!isBareImport(source)) {
        const resolved = resolveVirtualImport(source, importer);
        if (resolved === undefined) {
          throw new Error(`belgie: virtual import not found: ${JSON.stringify(source)} from ${JSON.stringify(normalizeDiagnosticPath(importer, virtualRoot))}`);
        }
        return resolved;
      }
      if (packageInternal(source)) {
        throw new Error(`belgie: internal package import is not allowed: ${JSON.stringify(source)}`);
      }
      if (!packageAllowed(source, dependencies)) {
        throw new Error(`belgie: package import is not allowlisted: ${JSON.stringify(source)}`);
      }
      const resolved = await this.resolve(source, importer, { skipSelf: true });
      if (resolved === null) {
        throw new Error(`belgie: allowlisted package could not be resolved: ${JSON.stringify(source)}`);
      }
      return resolved;
    },

    load(id) {
      const [fileName, query] = splitQuery(id);
      if (fileName === entryId) {
        return buildVirtualEntry(widgetId);
      }
      const source = sources.get(fileName);
      if (source === undefined) {
        return null;
      }
      return textualAssetModule(fileName, source, query) ?? source;
    },
  };
}

function normalizeDiagnosticPath(value: string, virtualRoot: string): string {
  const normalized = normalizePath(value);
  const prefix = `${normalizePath(virtualRoot)}/`;
  return normalized.replaceAll(prefix, "").replaceAll(normalizePath(virtualRoot), ".");
}

function normalizeBuildError(error: unknown, virtualRoot: string): Error {
  const message = error instanceof Error ? error.message : String(error);
  return new Error(normalizeDiagnosticPath(message, virtualRoot), { cause: error });
}

export async function buildWidgetWithVite(
  options: BuildWidgetOptions,
  viteBuild: ViteBuild,
): Promise<BuiltWidget> {
  if (!isAbsolute(options.root)) {
    throw new Error("belgie: widget build root must be absolute");
  }
  if (!hasDefaultExport(options.widget)) {
    throw new Error(`belgie: ${WIDGET_FILE} is missing a default export`);
  }

  const virtualRoot = normalizePath(resolve(options.root, VIRTUAL_DIRECTORY));
  const sources = new Map<string, string>([
    [normalizePath(resolve(virtualRoot, WIDGET_FILE)), options.widget],
  ]);
  for (const [fileName, source] of Object.entries(options.files ?? {})) {
    validateVirtualPath(fileName);
    if (typeof source !== "string") {
      throw new Error(`belgie: virtual file must contain text: ${JSON.stringify(fileName)}`);
    }
    sources.set(normalizePath(resolve(virtualRoot, fileName)), source);
  }

  const dependencies = new Set(DEFAULT_DEPENDENCIES);
  for (const dependency of options.dependencies ?? []) {
    if (typeof dependency !== "string" || dependency.length === 0 || !isBareImport(dependency) || dependency.includes(":")) {
      throw new Error(`belgie: invalid dependency alias: ${JSON.stringify(dependency)}`);
    }
    dependencies.add(dependency);
  }

  try {
    const result = await viteBuild({
      appType: "custom",
      configFile: false,
      envDir: false,
      logLevel: "silent",
      plugins: [virtualProjectPlugin(virtualRoot, sources, dependencies)],
      publicDir: false,
      resolve: { dedupe: ["react", "react-dom"] },
      root: options.root,
      server: {
        host: "127.0.0.1",
        fs: { allow: [options.root] },
      },
      build: {
        assetsInlineLimit: MAX_INLINE_ASSET_SIZE,
        copyPublicDir: false,
        cssCodeSplit: false,
        emptyOutDir: false,
        license: false,
        manifest: false,
        modulePreload: false,
        reportCompressedSize: false,
        sourcemap: false,
        ssrManifest: false,
        watch: null,
        write: false,
        rolldownOptions: {
          input: normalizePath(resolve(virtualRoot, ENTRY_FILE)),
          output: { codeSplitting: false },
        },
      },
    });
    if (Array.isArray(result)) {
      throw new Error(`belgie: expected one Vite build output, received ${result.length}`);
    }
    const output = (result as BuildOutput).output;
    return { html: renderWidgetBundle("virtual", output) };
  } catch (error) {
    throw normalizeBuildError(error, virtualRoot);
  }
}

export async function buildWidget(options: BuildWidgetOptions): Promise<BuiltWidget> {
  return buildWidgetWithVite(options, viteBuild);
}
