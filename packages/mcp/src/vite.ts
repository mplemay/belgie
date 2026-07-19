import { rmSync } from "node:fs";
import { isAbsolute, relative, resolve } from "node:path";

import { build, normalizePath, type Plugin, type ResolvedConfig, type UserConfig } from "vite";

import { buildVirtualEntry, renderWidgetHtmlDocument } from "./html.js";
import {
  assertNoInvalidWidgets,
  assertUniqueWidgetNames,
  scanWidgetsSync,
  type WidgetCandidate,
} from "./scan-widgets.js";
import { hasDefaultExport } from "./validate-widget.js";

const VIRTUAL_PREFIX = "/_belgie/widget/";
const VIRTUAL_MODULE_PREFIX = "\0belgie:widget:";
const ORCHESTRATION_ENTRY_ID = "belgie:widget-build-orchestrator";
const RESOLVED_ORCHESTRATION_ENTRY_ID = "\0belgie:widget-build-orchestrator";
const INTERNAL_WIDGET_PATH_ENV = "BELGIE_INTERNAL_WIDGET_PATH";
const MAX_INLINE_ASSET_SIZE = Number.MAX_SAFE_INTEGER;
const REACT_REFRESH_PLUGIN_NAME = "vite:react-refresh";
const TEXT_DECODER = new TextDecoder();

export type BelgiePluginOptions = {
  srcDir?: string;
};

type RollupInput = string | string[] | Record<string, string>;

type BuildAsset = {
  fileName: string;
  source: string | Uint8Array;
  type: "asset";
};

type BuildChunk = {
  code: string;
  dynamicImports: string[];
  facadeModuleId: string | null;
  fileName: string;
  imports: string[];
  isEntry: boolean;
  type: "chunk";
  viteMetadata?: { importedCss?: Set<string> };
};

type BuildArtifact = BuildAsset | BuildChunk;

function getWidgetEntryPattern(srcDir: string): RegExp {
  const escaped = normalizePath(srcDir).replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  return new RegExp(`${escaped}\/[^/]+\/widget\\.tsx(?:\\?.*)?$`);
}

function virtualWidgetName(id: string): string | undefined {
  if (!id.startsWith(VIRTUAL_PREFIX)) {
    return undefined;
  }
  return decodeURIComponent(id.slice(VIRTUAL_PREFIX.length).split("?", 1)[0] ?? "");
}

function readAsset(asset: BuildAsset): string {
  return typeof asset.source === "string" ? asset.source : TEXT_DECODER.decode(asset.source);
}

function renderWidgetBundle(name: string, bundle: Record<string, BuildArtifact>): string {
  const artifacts = Object.values(bundle);
  const chunks = artifacts.filter((artifact): artifact is BuildChunk => artifact.type === "chunk");
  const entries = chunks.filter((chunk) => chunk.isEntry);
  if (entries.length !== 1) {
    throw new Error(`belgie: expected one entry chunk for widget "${name}", received ${entries.length}`);
  }

  const entry = entries[0]!;
  const extraChunks = chunks.filter((chunk) => chunk !== entry);
  if (extraChunks.length > 0) {
    throw new Error(
      `belgie: widget "${name}" emitted extra chunks: ${extraChunks.map((chunk) => chunk.fileName).join(", ")}`,
    );
  }

  const imports = [...entry.imports, ...entry.dynamicImports].filter((item) => item !== entry.fileName);
  if (imports.length > 0) {
    throw new Error(`belgie: widget "${name}" retained imports: ${imports.join(", ")}`);
  }

  const assets = artifacts.filter((artifact): artifact is BuildAsset => artifact.type === "asset");
  const nonCssAssets = assets.filter((asset) => !asset.fileName.endsWith(".css"));
  if (nonCssAssets.length > 0) {
    throw new Error(
      `belgie: widget "${name}" emitted non-CSS assets: ${nonCssAssets.map((asset) => asset.fileName).join(", ")}`,
    );
  }

  const assetsByName = new Map(assets.map((asset) => [asset.fileName, asset]));
  const importedCss = [...(entry.viteMetadata?.importedCss ?? [])];
  const cssNames = importedCss.length > 0 ? importedCss : assets.map((asset) => asset.fileName).sort();
  const styles = cssNames.map((cssName) => {
    const asset = assetsByName.get(cssName);
    if (asset === undefined) {
      throw new Error(`belgie: widget "${name}" references missing CSS asset ${cssName}`);
    }
    return readAsset(asset);
  });
  return renderWidgetHtmlDocument({ inlineScript: entry.code, inlineStyles: styles });
}

function restoreEnvironment(name: string, previous: string | undefined): void {
  if (previous === undefined) {
    delete process.env[name];
  } else {
    process.env[name] = previous;
  }
}

function ensureReactRefreshPreamble(html: string, base: string, enabled: boolean): string {
  if (!enabled || html.includes("@react-refresh")) {
    return html;
  }
  const normalizedBase = base.endsWith("/") ? base : `${base}/`;
  const refreshPath = `${normalizedBase}@react-refresh`;
  const preamble = [
    '<script type="module">',
    `import { injectIntoGlobalHook } from ${JSON.stringify(refreshPath)};`,
    "injectIntoGlobalHook(window);",
    "window.$RefreshReg$ = () => {};",
    "window.$RefreshSig$ = () => (type) => type;",
    "</script>",
  ].join("\n");
  return html.replace("<head>", `<head>\n${preamble}`);
}

async function buildWidget(
  widget: WidgetCandidate,
  config: ResolvedConfig,
  configFile: string,
): Promise<void> {
  const previousWidgetPath = process.env[INTERNAL_WIDGET_PATH_ENV];
  process.env[INTERNAL_WIDGET_PATH_ENV] = widget.filePath;
  try {
    await build({
      configFile,
      configLoader: "native",
      root: config.root,
      mode: config.mode,
      ...(config.logLevel === undefined ? {} : { logLevel: config.logLevel }),
      build: {
        emptyOutDir: false,
        outDir: "dist",
      },
    });
  } finally {
    restoreEnvironment(INTERNAL_WIDGET_PATH_ENV, previousWidgetPath);
  }
}

export function belgie(options: BelgiePluginOptions = {}): Plugin {
  const rawSrcDir = options.srcDir ?? "src/widgets";
  const requestedWidgetPath = process.env[INTERNAL_WIDGET_PATH_ENV];
  let resolvedSrcDir = "";
  let projectRoot = "";
  let resolvedConfig: ResolvedConfig | undefined;
  let widgetMap = new Map<string, WidgetCandidate>();
  let widgetEntryPattern: RegExp | undefined;
  let usesOrchestrationEntry = false;
  let isBuildCommand = false;

  return {
    name: "belgie",
    enforce: "pre",
    api: { srcDir: rawSrcDir },

    config: {
      order: "post",
      handler(config: UserConfig, { command }) {
        isBuildCommand = command === "build";
        projectRoot = config.root || process.cwd();
        resolvedSrcDir = isAbsolute(rawSrcDir) ? rawSrcDir : resolve(projectRoot, rawSrcDir);
        widgetEntryPattern = getWidgetEntryPattern(resolvedSrcDir);

        const { valid, invalid } = scanWidgetsSync(resolvedSrcDir);
        assertUniqueWidgetNames(valid);
        if (command === "build") {
          assertNoInvalidWidgets(invalid);
        }

        if (requestedWidgetPath !== undefined) {
          const normalizedRequestedPath = normalizePath(resolve(requestedWidgetPath));
          const widget = valid.find((candidate) => normalizePath(resolve(candidate.filePath)) === normalizedRequestedPath);
          if (widget === undefined) {
            throw new Error(
              `belgie: isolated widget build requested unknown entry ${normalizePath(requestedWidgetPath)}`,
            );
          }
          widgetMap = new Map([[widget.name, widget]]);
          return {
            appType: "custom",
            resolve: { dedupe: ["react", "react-dom"] },
            build: {
              assetsInlineLimit: MAX_INLINE_ASSET_SIZE,
              copyPublicDir: false,
              cssCodeSplit: false,
              emptyOutDir: false,
              license: false,
              manifest: false,
              modulePreload: false,
              outDir: "dist",
              reportCompressedSize: false,
              sourcemap: false,
              ssrManifest: false,
              watch: null,
              write: true,
              rolldownOptions: {
                input: `${VIRTUAL_PREFIX}${encodeURIComponent(widget.name)}`,
                output: { codeSplitting: false },
              },
            },
          };
        }

        widgetMap = new Map(valid.map((widget) => [widget.name, widget]));
        const existingInput = config.build?.rolldownOptions?.input as RollupInput | undefined;
        usesOrchestrationEntry = existingInput === undefined;
        return {
          resolve: { dedupe: ["react", "react-dom"] },
          build: {
            rolldownOptions: {
              input: existingInput ?? ORCHESTRATION_ENTRY_ID,
            },
          },
          optimizeDeps: {
            entries: [`${resolvedSrcDir}/*/widget.tsx`],
            include: ["react", "react-dom/client", "react/jsx-runtime"],
          },
        };
      },
    },

    configResolved(config) {
      resolvedConfig = config;
      projectRoot = config.root;
      if (!resolvedSrcDir) {
        resolvedSrcDir = isAbsolute(rawSrcDir) ? rawSrcDir : resolve(projectRoot, rawSrcDir);
      }
    },

    resolveId(id) {
      if (id === ORCHESTRATION_ENTRY_ID) {
        return RESOLVED_ORCHESTRATION_ENTRY_ID;
      }
      const name = virtualWidgetName(id);
      if (name !== undefined && widgetMap.has(name)) {
        return `${VIRTUAL_MODULE_PREFIX}${name}`;
      }
      return null;
    },

    load(id) {
      if (id === RESOLVED_ORCHESTRATION_ENTRY_ID) {
        return "export {};\n";
      }
      if (id.startsWith(VIRTUAL_MODULE_PREFIX)) {
        const widget = widgetMap.get(id.slice(VIRTUAL_MODULE_PREFIX.length));
        if (widget !== undefined) {
          return buildVirtualEntry(widget.filePath);
        }
      }
      return null;
    },

    generateBundle: {
      order: "post",
      handler(_options, bundle) {
        if (requestedWidgetPath !== undefined) {
          const widget = [...widgetMap.values()][0];
          if (widget === undefined) {
            throw new Error("belgie: isolated widget build lost its widget entry");
          }
          const html = renderWidgetBundle(widget.name, bundle as Record<string, BuildArtifact>);
          for (const fileName of Object.keys(bundle)) {
            delete bundle[fileName];
          }
          this.emitFile({
            type: "asset",
            fileName: `widgets/${widget.name}/index.html`,
            source: html,
          });
          return;
        }

        if (usesOrchestrationEntry) {
          for (const [fileName, artifact] of Object.entries(bundle)) {
            if (artifact.type === "chunk" && artifact.facadeModuleId === RESOLVED_ORCHESTRATION_ENTRY_ID) {
              delete bundle[fileName];
            }
          }
        }
      },
    },

    async closeBundle() {
      if (!isBuildCommand || requestedWidgetPath !== undefined || resolvedConfig === undefined || widgetMap.size === 0) {
        return;
      }
      if (!resolvedConfig.configFile) {
        throw new Error(
          "belgie: isolated widget builds require a Vite config file; inline configs are not supported",
        );
      }
      rmSync(resolve(projectRoot, "dist", "widgets"), { recursive: true, force: true });
      for (const widget of widgetMap.values()) {
        await buildWidget(widget, resolvedConfig, resolvedConfig.configFile);
      }
    },

    configureServer(server) {
      if (!resolvedSrcDir) {
        const root = server.config.root || process.cwd();
        resolvedSrcDir = isAbsolute(rawSrcDir) ? rawSrcDir : resolve(root, rawSrcDir);
        projectRoot = root;
        widgetEntryPattern = getWidgetEntryPattern(resolvedSrcDir);
      }

      server.watcher.add(resolvedSrcDir);
      let knownInvalid = new Set<string>();
      const rescan = () => {
        try {
          const { valid, invalid } = scanWidgetsSync(resolvedSrcDir);
          const nextInvalid = new Set(invalid.map((widget) => widget.filePath));

          for (const filePath of nextInvalid) {
            if (!knownInvalid.has(filePath)) {
              server.config.logger.warn(
                `[belgie] widget file "${relative(projectRoot, filePath)}" is missing a default export — it won't be built until fixed.`,
              );
            }
          }
          for (const filePath of knownInvalid) {
            if (!nextInvalid.has(filePath)) {
              server.config.logger.info(`[belgie] widget file "${relative(projectRoot, filePath)}" resolved.`);
            }
          }
          knownInvalid = nextInvalid;

          assertUniqueWidgetNames(valid);
          widgetMap = new Map(valid.map((widget) => [widget.name, widget]));
        } catch (error) {
          const message = error instanceof Error ? error.message : String(error);
          server.config.logger.error(`[belgie] widget rescan failed: ${message}`);
        }
      };

      rescan();
      server.watcher.on("add", rescan);
      server.watcher.on("change", rescan);
      server.watcher.on("unlink", rescan);

      server.middlewares.use(async (request, response, next) => {
        try {
          const pathname = new URL(request.url ?? "/", "http://localhost").pathname;
          const match = /^\/widgets\/([^/]+)\/index\.html$/.exec(pathname);
          const name = match?.[1] === undefined ? undefined : decodeURIComponent(match[1]);
          if (name === undefined) {
            next();
            return;
          }
          if (!widgetMap.has(name)) {
            response.statusCode = 404;
            response.setHeader("Content-Type", "text/plain; charset=utf-8");
            response.end(`Unknown widget: ${name}`);
            return;
          }
          const transformedHtml = await server.transformIndexHtml(
            pathname,
            renderWidgetHtmlDocument({ scripts: [`${VIRTUAL_PREFIX}${encodeURIComponent(name)}`] }),
            request.url,
          );
          const html = ensureReactRefreshPreamble(
            transformedHtml,
            server.config.base,
            server.config.plugins.some((plugin) => plugin.name === REACT_REFRESH_PLUGIN_NAME),
          );
          response.statusCode = 200;
          response.setHeader("Content-Type", "text/html; charset=utf-8");
          response.end(html);
        } catch (error) {
          next(error);
        }
      });
    },

    transform(code, id) {
      if (widgetEntryPattern?.test(id) && !hasDefaultExport(code)) {
        this.warn(`Widget file "${id.split("/").pop()}" is missing a default export.`);
      }
      return null;
    },
  };
}
