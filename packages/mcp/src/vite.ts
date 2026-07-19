import { rmSync } from "node:fs";
import { isAbsolute, relative, resolve } from "node:path";

import type { OutputOptions } from "rolldown";
import { build, normalizePath } from "vite";
import type { Plugin, ResolvedConfig, UserConfig } from "vite";

import { renderWidgetBundle, type BuildArtifact } from "./bundle.js";
import { buildVirtualEntry, renderWidgetHtmlDocument } from "./html.js";
import { assertNoInvalidWidgets, assertUniqueWidgetNames, scanWidgetsSync } from "./scan-widgets.js";
import type { WidgetCandidate } from "./scan-widgets.js";
import { hasDefaultExport } from "./validate-widget.js";

const VIRTUAL_PREFIX = "/_belgie/widget/";
const VIRTUAL_MODULE_PREFIX = "\0belgie:widget:";
const ORCHESTRATION_ENTRY_ID = "belgie:widget-build-orchestrator";
const RESOLVED_ORCHESTRATION_ENTRY_ID = "\0belgie:widget-build-orchestrator";
const INTERNAL_PACKAGE_TYPE_ENV = "BELGIE_INTERNAL_PACKAGE_TYPE";
const INTERNAL_WIDGET_PATH_ENV = "BELGIE_INTERNAL_WIDGET_PATH";
const MAX_INLINE_ASSET_SIZE = Number.MAX_SAFE_INTEGER;
const MODULE_PACKAGE_TYPE = "module";
const REACT_REFRESH_PLUGIN_NAME = "vite:react-refresh";

export interface BelgiePluginOptions {
  srcDir?: string;
}

function restoreEnvironment(name: string, previous: string | undefined): void {
  if (previous === undefined) {
    delete process.env[name];
  } else {
    process.env[name] = previous;
  }
}

function moduleServerOutput(output: OutputOptions): OutputOptions {
  const entryFileNames =
    typeof output.entryFileNames === "string"
      ? output.entryFileNames.replace(/\.(?:c|m)?js$/u, ".js")
      : (output.entryFileNames ?? "[name].js");
  const chunkFileNames =
    typeof output.chunkFileNames === "string"
      ? output.chunkFileNames.replace(/\.(?:c|m)?js$/u, ".js")
      : (output.chunkFileNames ?? "assets/[name]-[hash].js");
  return {
    ...output,
    chunkFileNames,
    entryFileNames,
  };
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

async function buildWidget(widget: WidgetCandidate, config: ResolvedConfig, configFile: string): Promise<void> {
  const previousWidgetPath = process.env[INTERNAL_WIDGET_PATH_ENV];
  process.env[INTERNAL_WIDGET_PATH_ENV] = widget.filePath;
  try {
    await build({
      configFile,
      // Bundle the project config so package subpath imports used by framework plugins resolve before Deno loads it.
      configLoader: "bundle",
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
  const moduleMode = process.env[INTERNAL_PACKAGE_TYPE_ENV] === MODULE_PACKAGE_TYPE;
  const requestedWidgetPath = process.env[INTERNAL_WIDGET_PATH_ENV];
  let resolvedSrcDir = "";
  let projectRoot = "";
  let resolvedConfig: ResolvedConfig | undefined;
  let widgetMap = new Map<string, WidgetCandidate>();
  let widgetEntryPattern: RegExp | undefined;
  let usesOrchestrationEntry = false;
  let isBuildCommand = false;
  let widgetsBuilt = false;

  return {
    api: { srcDir: rawSrcDir },
    async closeBundle() {
      if (
        !isBuildCommand ||
        requestedWidgetPath !== undefined ||
        resolvedConfig === undefined ||
        widgetMap.size === 0 ||
        widgetsBuilt
      ) {
        return;
      }
      if (!resolvedConfig.configFile) {
        throw new Error("belgie: isolated widget builds require a Vite config file; inline configs are not supported");
      }
      rmSync(resolve(projectRoot, "dist", "widgets"), { recursive: true, force: true });
      for (const widget of widgetMap.values()) {
        await buildWidget(widget, resolvedConfig, resolvedConfig.configFile);
      }
      widgetsBuilt = true;
    },
    config: {
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
          const widget = valid.find(
            (candidate) => normalizePath(resolve(candidate.filePath)) === normalizedRequestedPath,
          );
          if (widget === undefined) {
            throw new Error(
              `belgie: isolated widget build requested unknown entry ${normalizePath(requestedWidgetPath)}`,
            );
          }
          widgetMap = new Map([[widget.name, widget]]);
          const isolatedBuild = {
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
          };
          return {
            appType: "custom",
            // Vite's legacy programmatic build selects the client environment when a framework defines several.
            environments: { client: { build: isolatedBuild } },
            resolve: { dedupe: ["react", "react-dom"] },
            build: isolatedBuild,
          };
        }

        widgetMap = new Map(valid.map((widget) => [widget.name, widget]));
        const existingInput = config.build?.rolldownOptions?.input;
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
      order: "post",
    },
    configResolved(config) {
      resolvedConfig = config;
      projectRoot = config.root;
      if (!resolvedSrcDir) {
        resolvedSrcDir = isAbsolute(rawSrcDir) ? rawSrcDir : resolve(projectRoot, rawSrcDir);
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
    enforce: "pre",
    generateBundle: {
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
      order: "post",
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
    name: "belgie",
    outputOptions: {
      handler(output) {
        if (moduleMode && this.environment.config.consumer === "server") {
          return moduleServerOutput(output);
        }
      },
      order: "post",
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
    transform(code, id) {
      const normalizedId = normalizePath(id);
      if (widgetEntryPattern?.test(normalizedId) && !hasDefaultExport(code)) {
        this.warn(`Widget file "${normalizedId.split("/").pop()}" is missing a default export.`);
      }
      return null;
    },
  };
}
