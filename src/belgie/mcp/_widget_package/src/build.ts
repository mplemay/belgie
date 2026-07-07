// Pinned esbuild-wasm subpath via npm: import; node_modules subpath resolution is unreliable here.
import * as esbuild from "npm:esbuild-wasm@0.24.2/esm/browser.js";

import { renderDocument } from "./html.ts";

type BuildOutputFile = {
  path: string;
  text: string;
};

type BuildResult = {
  outputFiles?: BuildOutputFile[];
};

type ResolveArgs = {
  importer: string;
  kind: string;
  path: string;
  resolveDir?: string;
};

let initialized = false;

export async function buildWidgetHtml(projectRoot: string, widgetPath: string): Promise<string> {
  if (!initialized) {
    await initialize(projectRoot);
    initialized = true;
  }
  const result = (await esbuild.build({
    bundle: true,
    format: "esm",
    jsx: "automatic",
    outdir: "out",
    plugins: [fileSystemPlugin(projectRoot)],
    stdin: {
      contents: `import widget from ${JSON.stringify(widgetPath)};\n\nwidget();\n`,
      loader: "tsx",
      sourcefile: "belgie-widget-entry.tsx",
    },
    write: false,
  })) as BuildResult;
  return renderBundle(result.outputFiles ?? []);
}

async function initialize(projectRoot: string): Promise<void> {
  const wasmPath = join(await resolvePackageRoot(projectRoot, "esbuild-wasm"), "esbuild.wasm");
  const wasmModule = await WebAssembly.compile(await Deno.readFile(wasmPath));
  await esbuild.initialize({
    wasmModule,
    worker: false,
  });
}

function renderBundle(outputFiles: BuildOutputFile[]): string {
  const scripts = outputFiles.filter((file) => file.path.endsWith(".js"));
  if (scripts.length !== 1) {
    throw new Error(`Belgie expected one widget script, got ${scripts.length}`);
  }
  const [script] = scripts;
  if (!script) {
    throw new Error("Belgie widget script was not emitted");
  }
  const unsupported = outputFiles.filter((file) => !file.path.endsWith(".js") && !file.path.endsWith(".css"));
  if (unsupported.length) {
    throw new Error(`Belgie widget emitted unsupported assets: ${unsupported.map((file) => file.path).join(", ")}`);
  }
  const styles = outputFiles.filter((file) => file.path.endsWith(".css")).map((file) => file.text);
  return renderDocument({ script: script.text, styles });
}

function fileSystemPlugin(projectRoot: string) {
  return {
    name: "belgie-file-system",
    setup(build) {
      build.onResolve({ filter: /.*/ }, (args: ResolveArgs) => resolveImport(projectRoot, args));
      build.onLoad({ filter: /.*/, namespace: "file" }, loadFile);
    },
  };
}

async function resolveImport(projectRoot: string, args: ResolveArgs) {
  if (args.kind === "entry-point") {
    return { namespace: "file", path: await resolveFile(join(projectRoot, args.path)) };
  }
  if (args.path.startsWith(".") || args.path.startsWith("/")) {
    const base = args.path.startsWith("/") ? "" : args.importer ? dirname(args.importer) : (args.resolveDir ?? projectRoot);
    return { namespace: "file", path: await resolveFile(resolvePath(base, args.path)) };
  }
  return { namespace: "file", path: await resolvePackage(projectRoot, args.path) };
}

async function loadFile(args: { path: string }) {
  const contents = await Deno.readTextFile(args.path);
  return {
    contents,
    loader: loaderFor(args.path),
    resolveDir: dirname(args.path),
  };
}

async function resolvePackage(projectRoot: string, specifier: string): Promise<string> {
  const { name, subpath } = parsePackageSpecifier(specifier);
  const packageRoot = await resolvePackageRoot(projectRoot, name);
  const packageJson = JSON.parse(await Deno.readTextFile(join(packageRoot, "package.json")));
  const target = packageTarget(packageJson, subpath);
  return resolveFile(join(packageRoot, target.replace(/^\.\//, "")));
}

async function resolvePackageRoot(projectRoot: string, name: string): Promise<string> {
  const directRoot = join(projectRoot, "node_modules", name);
  if (await isDirectory(directRoot)) {
    return directRoot;
  }
  const denoRoot = join(projectRoot, "node_modules", ".deno");
  if (await isDirectory(denoRoot)) {
    for await (const entry of Deno.readDir(denoRoot)) {
      const candidate = join(denoRoot, entry.name, "node_modules", name);
      if (await isDirectory(candidate)) {
        return candidate;
      }
    }
  }
  return directRoot;
}

function parsePackageSpecifier(specifier: string): { name: string; subpath: string } {
  const parts = specifier.split("/");
  if (specifier.startsWith("@")) {
    return {
      name: `${parts[0]}/${parts[1]}`,
      subpath: parts.slice(2).join("/"),
    };
  }
  return { name: parts[0] ?? specifier, subpath: parts.slice(1).join("/") };
}

function packageTarget(packageJson, subpath: string): string {
  if (packageJson.exports) {
    const key = subpath ? `./${subpath}` : ".";
    const target = pickExport(packageJson.exports[key] ?? (subpath ? undefined : packageJson.exports));
    if (target) {
      return target;
    }
  }
  if (subpath) {
    return `./${subpath}`;
  }
  return packageJson.module ?? packageJson.main ?? "index.js";
}

function pickExport(value): string | null {
  if (typeof value === "string") {
    return value;
  }
  if (!value || typeof value !== "object") {
    return null;
  }
  return value.browser ?? value.import ?? value.default ?? value.require ?? pickExport(Object.values(value)[0]);
}

async function resolveFile(path: string): Promise<string> {
  if (await isFile(path)) {
    return path;
  }
  for (const extension of [".tsx", ".ts", ".jsx", ".js", ".mjs", ".cjs", ".json", ".css"]) {
    if (await isFile(`${path}${extension}`)) {
      return `${path}${extension}`;
    }
  }
  if (await isDirectory(path)) {
    try {
      const packageJson = JSON.parse(await Deno.readTextFile(join(path, "package.json")));
      return resolveFile(join(path, packageTarget(packageJson, "")));
    } catch {
      return resolveFile(join(path, "index"));
    }
  }
  throw new Error(`Could not resolve ${path}`);
}

async function isFile(path: string): Promise<boolean> {
  try {
    return (await Deno.stat(path)).isFile;
  } catch {
    return false;
  }
}

async function isDirectory(path: string): Promise<boolean> {
  try {
    return (await Deno.stat(path)).isDirectory;
  } catch {
    return false;
  }
}

function loaderFor(path: string): string {
  const extension = path.split(".").pop();
  return {
    css: "css",
    cjs: "js",
    js: "js",
    json: "json",
    jsx: "jsx",
    mjs: "js",
    ts: "ts",
    tsx: "tsx",
  }[extension ?? ""] ?? "js";
}

function dirname(path: string): string {
  const index = path.lastIndexOf("/");
  return index <= 0 ? "/" : path.slice(0, index);
}

function join(...parts: string[]): string {
  return parts.join("/").replaceAll(/\/+/g, "/");
}

function resolvePath(base: string, specifier: string): string {
  return decodeURIComponent(new URL(specifier, `file://${base}/`).pathname);
}

export default buildWidgetHtml;
