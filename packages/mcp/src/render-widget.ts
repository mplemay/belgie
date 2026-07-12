import { isAbsolute, resolve } from "node:path";

import {
  build,
  loadConfigFromFile,
  mergeConfig,
  normalizePath,
  version as viteVersion,
  type InlineConfig,
  type Plugin,
  type PluginOption,
  type UserConfig,
} from "vite";

import { buildVirtualEntry, renderWidgetHtmlDocument } from "./html.js";

const VIRTUAL_ENTRY_ID = "belgie:embedded-widget-entry";
const RESOLVED_VIRTUAL_ENTRY_ID = "\0belgie:embedded-widget-entry";
const DEFAULT_WIDGET_FILENAME = "__belgie_widget__.tsx";
const MAX_INLINE_ASSET_SIZE = Number.MAX_SAFE_INTEGER;
const TEXT_DECODER = new TextDecoder();

type BuildAsset = {
  fileName: string;
  source: string | Uint8Array;
  type: "asset";
};

type BuildChunk = {
  code: string;
  dynamicImports: string[];
  fileName: string;
  imports: string[];
  isEntry: boolean;
  type: "chunk";
  viteMetadata?: { importedCss?: Set<string> };
};

type BuildArtifact = BuildAsset | BuildChunk;
type BuildOutput = { output: BuildArtifact[] };

export type RenderWidgetOptions = {
  configFile?: string | false;
  filename?: string;
  root: string;
  source: string;
};

function embeddedWidgetPlugin(source: string, filename: string): Plugin {
  const normalizedFilename = normalizePath(filename);
  return {
    name: "belgie:embedded-widget",
    enforce: "pre",
    resolveId(id) {
      if (id === VIRTUAL_ENTRY_ID) {
        return RESOLVED_VIRTUAL_ENTRY_ID;
      }
      if (normalizePath(id) === normalizedFilename) {
        return normalizedFilename;
      }
      return null;
    },
    load(id) {
      if (id === RESOLVED_VIRTUAL_ENTRY_ID) {
        return buildVirtualEntry(normalizedFilename);
      }
      if (normalizePath(id) === normalizedFilename) {
        return source;
      }
      return null;
    },
  };
}

async function flattenPlugins(options: PluginOption[] | undefined): Promise<Plugin[]> {
  const plugins: Plugin[] = [];
  for (const option of options ?? []) {
    plugins.push(...(await flattenPlugin(option)));
  }
  return plugins;
}

async function flattenPlugin(option: PluginOption): Promise<Plugin[]> {
  const resolved = await option;
  if (!resolved) {
    return [];
  }
  if (Array.isArray(resolved)) {
    const nested = await Promise.all(resolved.map((entry) => flattenPlugin(entry)));
    return nested.flat();
  }
  return [resolved];
}

function copyDefined<T extends object, K extends keyof T>(source: T, keys: K[]): Pick<T, K> {
  const result = {} as Pick<T, K>;
  for (const key of keys) {
    if (source[key] !== undefined) {
      result[key] = source[key];
    }
  }
  return result;
}

function safeUserConfig(config: UserConfig): InlineConfig {
  const safe = copyDefined(config, [
    "assetsInclude",
    "css",
    "define",
    "envDir",
    "envPrefix",
    "esbuild",
    "json",
    "oxc",
    "resolve",
  ]);
  const buildOptions = config.build
    ? copyDefined(config.build, [
        "commonjsOptions",
        "cssMinify",
        "cssTarget",
        "dynamicImportVarsOptions",
        "minify",
        "target",
        "terserOptions",
      ])
    : undefined;
  return buildOptions === undefined ? safe : { ...safe, build: buildOptions };
}

async function loadUserConfig(
  root: string,
  configFile: string | false | undefined,
): Promise<{ config: InlineConfig; plugins: Plugin[] }> {
  if (configFile === false) {
    return { config: {}, plugins: [] };
  }
  const explicitConfig = configFile === undefined ? undefined : isAbsolute(configFile) ? configFile : resolve(root, configFile);
  const loaded = await loadConfigFromFile(
    { command: "build", mode: "production" },
    explicitConfig,
    root,
    "error",
    undefined,
    "native",
  );
  if (loaded === null) {
    return { config: {}, plugins: [] };
  }
  const plugins = (await flattenPlugins(loaded.config.plugins)).filter((plugin) => plugin.name !== "belgie");
  return { config: safeUserConfig(loaded.config), plugins };
}

function singleChunkBuildOptions(): Pick<InlineConfig, "build"> {
  return {
    build: {
      rolldownOptions: {
        input: VIRTUAL_ENTRY_ID,
        output: { codeSplitting: false },
      },
    },
  };
}

function controlledConfig(root: string): InlineConfig {
  return mergeConfig(
    {
      appType: "custom",
      configFile: false,
      logLevel: "error",
      resolve: { dedupe: ["react", "react-dom"] },
      root,
      server: { host: "127.0.0.1" },
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
      },
    },
    singleChunkBuildOptions(),
  );
}

function enforceEmbeddedOutputPlugin(root: string): Plugin {
  return {
    name: "belgie:embedded-output",
    config: {
      order: "post",
      handler() {
        return controlledConfig(root);
      },
    },
  };
}

function normalizeOutputs(value: unknown): BuildOutput[] {
  const outputs = Array.isArray(value) ? value : [value];
  return outputs.map((output) => {
    if (typeof output !== "object" || output === null || !("output" in output) || !Array.isArray(output.output)) {
      throw new Error("Belgie does not support watch-mode embedded widget output.");
    }
    return output as BuildOutput;
  });
}

function readAsset(asset: BuildAsset): string {
  return typeof asset.source === "string" ? asset.source : TEXT_DECODER.decode(asset.source);
}

function renderBuildOutput(outputs: BuildOutput[]): string {
  const artifacts = outputs.flatMap((output) => output.output);
  const chunks = artifacts.filter((artifact): artifact is BuildChunk => artifact.type === "chunk");
  const entries = chunks.filter((chunk) => chunk.isEntry);
  if (entries.length !== 1) {
    throw new Error(`Belgie expected one embedded widget entry chunk, received ${entries.length}.`);
  }
  const entry = entries[0]!;
  const extraChunks = chunks.filter((chunk) => chunk !== entry);
  if (extraChunks.length > 0) {
    throw new Error(`Belgie embedded widget emitted extra chunks: ${extraChunks.map((chunk) => chunk.fileName).join(", ")}`);
  }
  const imports = [...entry.imports, ...entry.dynamicImports].filter((item) => item !== entry.fileName);
  if (imports.length > 0) {
    throw new Error(`Belgie embedded widget retained imports: ${imports.join(", ")}`);
  }
  const assets = artifacts.filter((artifact): artifact is BuildAsset => artifact.type === "asset");
  const nonCssAssets = assets.filter((asset) => !asset.fileName.endsWith(".css"));
  if (nonCssAssets.length > 0) {
    throw new Error(
      `Belgie embedded widget emitted non-CSS assets: ${nonCssAssets.map((asset) => asset.fileName).join(", ")}`,
    );
  }
  const assetsByName = new Map(assets.map((asset) => [asset.fileName, asset]));
  const importedCss = [...(entry.viteMetadata?.importedCss ?? [])];
  const cssNames = importedCss.length > 0 ? importedCss : assets.map((asset) => asset.fileName).sort();
  const styles = cssNames.map((name) => {
    const asset = assetsByName.get(name);
    if (asset === undefined) {
      throw new Error(`Belgie embedded widget references missing CSS asset ${name}.`);
    }
    return readAsset(asset);
  });
  return renderWidgetHtmlDocument({ inlineScript: entry.code, inlineStyles: styles });
}

export async function renderWidget(options: RenderWidgetOptions): Promise<string> {
  if (Number.parseInt(viteVersion.split(".", 1)[0] ?? "0", 10) < 8) {
    throw new Error(`Belgie embedded widgets require Vite 8 or newer; found ${viteVersion}.`);
  }
  const root = resolve(options.root);
  const filename = normalizePath(resolve(root, options.filename ?? DEFAULT_WIDGET_FILENAME));
  const user = await loadUserConfig(root, options.configFile);
  const controlled = controlledConfig(root);
  controlled.plugins = [
    embeddedWidgetPlugin(options.source, filename),
    ...user.plugins,
    enforceEmbeddedOutputPlugin(root),
  ];
  const config = mergeConfig(user.config, controlled);
  return renderBuildOutput(normalizeOutputs(await build(config)));
}
