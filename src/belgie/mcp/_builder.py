import shutil
from importlib.resources import as_file, files
from json import dumps
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Final

from belgie import Environment, Runtime, Script

BUILD_DEPENDENCIES: Final[dict[str, str]] = {
    "@modelcontextprotocol/ext-apps": "latest",
    "@modelcontextprotocol/sdk": "latest",
    "esbuild-wasm-browser": "npm:esbuild-wasm@0.24.2/esm/browser.js",
    "react": "^19",
    "react-dom": "^19",
}
ESBUILD_SCRIPT: Final[str] = """
import * as esbuild from "esbuild-wasm-browser";

let initialized = false;

export default async function build(projectRoot, entryPoint) {
  if (!initialized) {
    await initialize();
    initialized = true;
  }
  const result = await esbuild.build({
    bundle: true,
    entryPoints: [entryPoint],
    format: "esm",
    jsx: "automatic",
    outdir: "out",
    plugins: [fileSystemPlugin(projectRoot)],
    write: false,
  });
  return result.outputFiles.map((file) => ({ path: file.path, text: file.text }));
}

async function initialize() {
  const wasmPath = new URL(
    "./node_modules/.deno/esbuild-wasm@0.24.2/node_modules/esbuild-wasm/esbuild.wasm",
    import.meta.url,
  );
  const wasmModule = await WebAssembly.compile(await Deno.readFile(wasmPath));
  await esbuild.initialize({
    wasmModule,
    worker: false,
  });
}

function fileSystemPlugin(projectRoot) {
  return {
    name: "belgie-file-system",
    setup(build) {
      build.onResolve({ filter: /.*/ }, (args) => resolveImport(projectRoot, args));
      build.onLoad({ filter: /.*/, namespace: "file" }, loadFile);
    },
  };
}

async function resolveImport(projectRoot, args) {
  if (args.kind === "entry-point") {
    return { namespace: "file", path: await resolveFile(join(projectRoot, args.path)) };
  }
  if (args.path.startsWith(".") || args.path.startsWith("/")) {
    const base = args.path.startsWith("/") ? "" : dirname(args.importer);
    return { namespace: "file", path: await resolveFile(resolvePath(base, args.path)) };
  }
  return { namespace: "file", path: await resolvePackage(projectRoot, args.path) };
}

async function loadFile(args) {
  const contents = await Deno.readTextFile(args.path);
  return {
    contents,
    loader: loaderFor(args.path),
    resolveDir: dirname(args.path),
  };
}

async function resolvePackage(projectRoot, specifier) {
  const { name, subpath } = parsePackageSpecifier(specifier);
  const packageRoot = await resolvePackageRoot(projectRoot, name);
  const packageJson = JSON.parse(await Deno.readTextFile(join(packageRoot, "package.json")));
  const target = packageTarget(packageJson, subpath);
  return resolveFile(join(packageRoot, target.replace(/^\\.\\//, "")));
}

async function resolvePackageRoot(projectRoot, name) {
  const directRoot = join(projectRoot, "node_modules", name);
  if (await isDirectory(directRoot)) {
    return directRoot;
  }
  const denoRoot = join(projectRoot, "node_modules", ".deno");
  for await (const entry of Deno.readDir(denoRoot)) {
    const candidate = join(denoRoot, entry.name, "node_modules", name);
    if (await isDirectory(candidate)) {
      return candidate;
    }
  }
  return directRoot;
}

function parsePackageSpecifier(specifier) {
  const parts = specifier.split("/");
  if (specifier.startsWith("@")) {
    return {
      name: `${parts[0]}/${parts[1]}`,
      subpath: parts.slice(2).join("/"),
    };
  }
  return { name: parts[0], subpath: parts.slice(1).join("/") };
}

function packageTarget(packageJson, subpath) {
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

function pickExport(value) {
  if (typeof value === "string") {
    return value;
  }
  if (!value || typeof value !== "object") {
    return null;
  }
  return value.browser ?? value.import ?? value.default ?? value.require ?? pickExport(Object.values(value)[0]);
}

async function resolveFile(path) {
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

async function isFile(path) {
  try {
    return (await Deno.stat(path)).isFile;
  } catch {
    return false;
  }
}

async function isDirectory(path) {
  try {
    return (await Deno.stat(path)).isDirectory;
  } catch {
    return false;
  }
}

function loaderFor(path) {
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
  }[extension] ?? "js";
}

function dirname(path) {
  const index = path.lastIndexOf("/");
  return index <= 0 ? "/" : path.slice(0, index);
}

function join(...parts) {
  return parts.join("/").replaceAll(/\\/+/g, "/");
}

function resolvePath(base, specifier) {
  return decodeURIComponent(new URL(specifier, `file://${base}/`).pathname);
}
"""
COPY_IGNORE_PATTERNS: Final[tuple[str, ...]] = ("node_modules", "dist", ".git")
WIDGET_PATH_OUTSIDE_ROOT_ERROR: Final[str] = "Widget path must stay inside the BelgieExtension root"


def build_widget_html(*, root: Path, path: Path) -> str:
    root_path = root.resolve(strict=True)
    widget_path = (root_path / path).resolve(strict=True)
    try:
        relative_widget_path = widget_path.relative_to(root_path)
    except ValueError as error:
        raise ValueError(WIDGET_PATH_OUTSIDE_ROOT_ERROR) from error

    with (
        as_file(files("belgie.mcp._widget_package")) as widget_package_path,
        TemporaryDirectory(prefix="belgie-mcp-") as temp_dir,
    ):
        project_path = Path(temp_dir)
        source_path = project_path / "source"
        shutil.copytree(
            root_path,
            source_path,
            ignore=shutil.ignore_patterns(*COPY_IGNORE_PATTERNS),
        )
        _write_build_project(
            project_path=project_path,
            widget_import=f"../source/{relative_widget_path.as_posix()}",
        )
        _run_bundle(project_path=project_path, widget_package_path=widget_package_path)
        return _render_html(project_path / "dist")


def _write_build_project(*, project_path: Path, widget_import: str) -> None:
    src_path = project_path / "src"
    src_path.mkdir()
    (project_path / "index.html").write_text(
        '<!doctype html><html><head><meta charset="utf-8"></head><body><div id="root"></div>'
        '<script type="module" src="/src/main.tsx"></script></body></html>\n',
        encoding="utf-8",
    )
    (src_path / "main.tsx").write_text(
        f"import widget from {dumps(widget_import)};\n\nwidget();\n",
        encoding="utf-8",
    )
    (project_path / "tsconfig.json").write_text(
        """
{
  "compilerOptions": {
    "jsx": "react-jsx",
    "jsxImportSource": "react"
  }
}
""".lstrip(),
        encoding="utf-8",
    )


def _run_bundle(*, project_path: Path, widget_package_path: Path) -> None:
    with Environment(BUILD_DEPENDENCIES, path=project_path) as env:
        env.install()
        _install_widget_package(project_path=project_path, widget_package_path=widget_package_path)
        (project_path / "dist").mkdir()
        with Runtime(env=env) as runtime:
            outputs = runtime(Script(ESBUILD_SCRIPT))(
                str(project_path),
                "src/main.tsx",
            )
    _write_outputs(dist_path=project_path / "dist", outputs=outputs)


def _install_widget_package(*, project_path: Path, widget_package_path: Path) -> None:
    destination = project_path / "node_modules" / "@belgie" / "widget"
    if destination.exists():
        shutil.rmtree(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(widget_package_path, destination)


def _write_outputs(*, dist_path: Path, outputs: list[dict[str, str]]) -> None:
    for output in outputs:
        path = Path(output["path"])
        suffix = path.suffix
        if suffix == ".js":
            name = "bundle.js"
        elif suffix == ".css":
            name = "bundle.css"
        else:
            continue
        (dist_path / name).write_text(output["text"], encoding="utf-8")


def _render_html(dist_path: Path) -> str:
    script = (dist_path / "bundle.js").read_text(encoding="utf-8").replace("</script", "<\\/script")
    stylesheet_path = dist_path / "bundle.css"
    stylesheet = ""
    if stylesheet_path.is_file():
        stylesheet = stylesheet_path.read_text(encoding="utf-8").replace("</style", "<\\/style")
    return (
        '<!doctype html><html><head><meta charset="utf-8">'
        f'<style>{stylesheet}</style></head><body><div id="root"></div>'
        f'<script type="module">{script}</script></body></html>\n'
    )
