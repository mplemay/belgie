import { mkdirSync, writeFileSync } from "node:fs";
import { isAbsolute, join, relative, resolve } from "node:path";

import type { Plugin, ResolvedConfig, UserConfig } from "vite";

import { buildVirtualEntry, renderWidgetHtmlDocument } from "./html.js";
import {
  assertNoInvalidWidgets,
  assertUniqueWidgetNames,
  scanWidgetsSync,
  type WidgetCandidate,
} from "./scan-widgets.js";
import { hasDefaultExport } from "./validate-widget.js";

export { renderWidget, type RenderWidgetOptions } from "./render-widget.js";

const VIRTUAL_PREFIX = "/_belgie/widget/";
const VIRTUAL_MODULE_PREFIX = "\0belgie:widget:";

export type BelgiePluginOptions = {
  srcDir?: string;
};

type ViteManifestChunk = {
  file: string;
  css?: string[];
  isEntry?: boolean;
};

type ViteManifest = Record<string, ViteManifestChunk>;

type RollupInput = string | string[] | Record<string, string>;

type WriteWidgetHtmlOptions = {
  outDir: string;
  base: string;
  widgets: WidgetCandidate[];
  manifest: ViteManifest;
};

function getWidgetEntryPattern(srcDir: string): RegExp {
  const escaped = srcDir.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  return new RegExp(
    `${escaped}\\/(?:[^/]+\\.(?:jsx|tsx)|[^/]+\\/index\\.(?:tsx|jsx))(?:\\?.*)?$`,
  );
}

function mergeRollupInput(existing: RollupInput | undefined, widgets: WidgetCandidate[]): Record<string, string> {
  const input: Record<string, string> = {};
  if (typeof existing === "string") {
    input.main = existing;
  } else if (Array.isArray(existing)) {
    for (const entry of existing) {
      input[entry] = entry;
    }
  } else if (existing && typeof existing === "object") {
    Object.assign(input, existing);
  }
  for (const widget of widgets) {
    input[widget.name] = `${VIRTUAL_PREFIX}${widget.name}`;
  }
  return input;
}

function assetHref(fileName: string, base: string): string {
  const normalizedBase = base.endsWith("/") ? base.slice(0, -1) : base;
  const path = fileName.startsWith("/") ? fileName : `/${fileName}`;
  if (!normalizedBase || normalizedBase === ".") {
    return path;
  }
  return `${normalizedBase}${path}`;
}

function writeWidgetHtmlFiles(options: WriteWidgetHtmlOptions): void {
  for (const widget of options.widgets) {
    const chunk =
      options.manifest[`${widget.name}.js`] ??
      options.manifest[widget.name] ??
      Object.values(options.manifest).find((entry) => entry.isEntry && entry.file.includes(widget.name));
    if (!chunk) {
      throw new Error(`belgie: missing Vite manifest entry for widget "${widget.name}"`);
    }

    const html = renderWidgetHtmlDocument({
      scripts: [assetHref(chunk.file, options.base)],
      styles: (chunk.css ?? []).map((file) => assetHref(file, options.base)),
    });
    const widgetDir = join(options.outDir, "widgets", widget.name);
    mkdirSync(widgetDir, { recursive: true });
    writeFileSync(join(widgetDir, "index.html"), html, "utf-8");
  }
}

export function belgie(options: BelgiePluginOptions = {}): Plugin {
  const rawSrcDir = options.srcDir ?? "src/widgets";
  let resolvedSrcDir = "";
  let projectRoot = "";
  let outDir = "";
  let base = "/";
  let widgetMap = new Map<string, WidgetCandidate>();
  let widgetEntryPattern: RegExp | undefined;

  return {
    name: "belgie",
    enforce: "pre",
    api: { srcDir: rawSrcDir },

    config(config: UserConfig, { command }) {
      projectRoot = config.root || process.cwd();
      resolvedSrcDir = isAbsolute(rawSrcDir) ? rawSrcDir : resolve(projectRoot, rawSrcDir);
      widgetEntryPattern = getWidgetEntryPattern(resolvedSrcDir);

      const { valid, invalid } = scanWidgetsSync(resolvedSrcDir);
      assertUniqueWidgetNames(valid);
      if (command === "build") {
        assertNoInvalidWidgets(invalid);
      }
      widgetMap = new Map(valid.map((widget) => [widget.name, widget]));

      const existingInput = config.build?.rollupOptions?.input as RollupInput | undefined;
      const input = mergeRollupInput(existingInput, valid);

      return {
        resolve: {
          dedupe: ["react", "react-dom"],
        },
        build: {
          manifest: true,
          cssCodeSplit: false,
          emptyOutDir: config.build?.emptyOutDir ?? false,
          rollupOptions: {
            input,
          },
        },
        optimizeDeps: {
          entries: [
            `${resolvedSrcDir}/*.{tsx,jsx}`,
            `${resolvedSrcDir}/*/index.{tsx,jsx}`,
          ],
          include: ["react", "react-dom/client", "react/jsx-runtime"],
        },
      };
    },

    configResolved(config: ResolvedConfig) {
      projectRoot = config.root;
      outDir = config.build.outDir;
      base = config.base;
      if (!resolvedSrcDir) {
        resolvedSrcDir = isAbsolute(rawSrcDir) ? rawSrcDir : resolve(projectRoot, rawSrcDir);
      }
    },

    resolveId(id) {
      if (id.startsWith(VIRTUAL_PREFIX)) {
        const name = id.slice(VIRTUAL_PREFIX.length);
        if (widgetMap.has(name)) {
          return `${VIRTUAL_MODULE_PREFIX}${name}`;
        }
      }
      return null;
    },

    load(id) {
      if (id.startsWith(VIRTUAL_MODULE_PREFIX)) {
        const name = id.slice(VIRTUAL_MODULE_PREFIX.length);
        const widget = widgetMap.get(name);
        if (widget) {
          return buildVirtualEntry(widget.filePath);
        }
      }
      return null;
    },

    writeBundle(_options, bundle) {
      const widgets = [...widgetMap.values()];
      if (widgets.length === 0) {
        return;
      }

      const manifestAsset = bundle[".vite/manifest.json"];
      if (!manifestAsset || manifestAsset.type !== "asset") {
        throw new Error("belgie: Vite manifest was not emitted; enable build.manifest");
      }
      const source = manifestAsset.source;
      const manifestJson = typeof source === "string" ? source : new TextDecoder().decode(source);
      const manifest = JSON.parse(manifestJson) as ViteManifest;
      writeWidgetHtmlFiles({
        outDir,
        base,
        widgets,
        manifest,
      });
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
              server.config.logger.info(
                `[belgie] widget file "${relative(projectRoot, filePath)}" resolved.`,
              );
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
    },

    transform(code, id) {
      if (widgetEntryPattern?.test(id) && !hasDefaultExport(code)) {
        this.warn(`Widget file "${id.split("/").pop()}" is missing a default export.`);
      }
      return null;
    },
  };
}
