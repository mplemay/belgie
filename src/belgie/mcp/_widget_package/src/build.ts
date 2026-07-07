import { createRequire } from "node:module";
import { join, resolve } from "node:path";
import react from "@vitejs/plugin-react";
import { build, type Plugin } from "vite";
import { viteSingleFile } from "vite-plugin-singlefile";

import { renderDocument, renderWidgetBootstrap } from "./html.ts";
import { WIDGET_RENDER_MANIFEST, type WidgetRenderManifest } from "./manifest.ts";

const VIRTUAL_HTML_PATH = "__belgie_virtual__/index.html";
const VIRTUAL_WIDGET_ENTRY_ID = "belgie:widget-entry";
const VIRTUAL_SOURCE_WIDGET_ID = "belgie:source-widget";
const RESOLVED_WIDGET_ENTRY_ID = "\0belgie:widget-entry";
const EXTERNAL_ASSET_PATTERNS = [
  'src="/assets/',
  'href="/assets/',
  'src="./assets/',
  'href="./assets/',
  'src="assets/',
  'href="assets/',
];

type OutputChunk = {
  code: string;
  fileName: string;
  type: "chunk";
};

type OutputAsset = {
  fileName: string;
  source: string | Uint8Array;
  type: "asset";
};

type BuildOutput = {
  output: Array<OutputAsset | OutputChunk>;
};

export type WidgetBuildResult = {
  html: string;
  manifest: WidgetRenderManifest;
};

function toVitePath(path: string): string {
  return path.replaceAll("\\", "/");
}

function resolveFromProjectNodeModules(projectRoot: string, specifier: string): string {
  const require = createRequire(join(projectRoot, "package.json"));
  return toVitePath(require.resolve(specifier));
}

function isBarePackageSpecifier(specifier: string): boolean {
  return (
    !specifier.startsWith(".") &&
    !specifier.startsWith("/") &&
    !specifier.startsWith("\0") &&
    !specifier.includes(":")
  );
}

function belgieVirtualInputPlugin(options: {
  virtualHtmlId: string;
  widgetFileId: string;
}): Plugin {
  return {
    name: "belgie:virtual-widget-input",
    enforce: "pre",
    resolveId(id) {
      const normalizedId = toVitePath(id);
      if (normalizedId === options.virtualHtmlId) {
        return options.virtualHtmlId;
      }
      if (id === VIRTUAL_WIDGET_ENTRY_ID) {
        return RESOLVED_WIDGET_ENTRY_ID;
      }
      if (id === VIRTUAL_SOURCE_WIDGET_ID) {
        return options.widgetFileId;
      }
    },
    load(id) {
      const normalizedId = toVitePath(id);
      if (normalizedId === options.virtualHtmlId) {
        return renderDocument({
          inlineScript: renderWidgetBootstrap(VIRTUAL_WIDGET_ENTRY_ID),
        });
      }
      if (id === RESOLVED_WIDGET_ENTRY_ID) {
        return [
          `import widget from ${JSON.stringify(VIRTUAL_SOURCE_WIDGET_ID)};`,
          "",
          "export default widget;",
          "",
        ].join("\n");
      }
    },
  };
}

function belgieWidgetDependencyPlugin(options: {
  projectRoot: string;
  widgetSourceRoot: string;
}): Plugin {
  return {
    name: "belgie:widget-dependencies",
    enforce: "pre",
    async resolveId(id, importer, resolveOptions) {
      if (!importer || !isBarePackageSpecifier(id)) {
        return null;
      }
      const normalizedImporter = toVitePath(importer);
      const normalizedWidgetRoot = toVitePath(options.widgetSourceRoot);
      if (!normalizedImporter.startsWith(normalizedWidgetRoot)) {
        return null;
      }
      const resolved = await this.resolve(id, importer, { ...resolveOptions, skipSelf: true });
      if (resolved) {
        return resolved;
      }
      return resolveFromProjectNodeModules(options.projectRoot, id);
    },
  };
}

function collectOutput(buildResult: unknown): Array<OutputAsset | OutputChunk> {
  const outputs = Array.isArray(buildResult) ? buildResult : [buildResult];
  return outputs.flatMap((result) => (result as BuildOutput).output ?? []);
}

function readAssetSource(asset: OutputAsset): string {
  if (typeof asset.source === "string") {
    return asset.source;
  }
  return new TextDecoder().decode(asset.source);
}

function extractHtml(buildResult: unknown): string {
  const htmlAssets = collectOutput(buildResult).filter(
    (item): item is OutputAsset => item.type === "asset" && item.fileName.endsWith(".html"),
  );
  if (htmlAssets.length !== 1) {
    throw new Error(`Belgie widget build produced ${htmlAssets.length} HTML documents.`);
  }
  const html = readAssetSource(htmlAssets[0]);
  if (EXTERNAL_ASSET_PATTERNS.some((pattern) => html.includes(pattern))) {
    throw new Error("Belgie widget build did not produce a fully inlined HTML document.");
  }
  return html;
}

export async function buildWidget(projectRoot: string, sourceRoot: string, widgetPath: string): Promise<WidgetBuildResult> {
  const normalizedProjectRoot = toVitePath(projectRoot);
  const virtualHtmlId = toVitePath(join(projectRoot, VIRTUAL_HTML_PATH));
  const widgetFileId = toVitePath(resolve(sourceRoot, widgetPath));
  const buildResult = await build({
    root: normalizedProjectRoot,
    configFile: false,
    logLevel: "error",
    resolve: {
      dedupe: ["react", "react-dom"],
    },
    plugins: [
      belgieVirtualInputPlugin({
        virtualHtmlId,
        widgetFileId,
      }),
      belgieWidgetDependencyPlugin({
        projectRoot: normalizedProjectRoot,
        widgetSourceRoot: toVitePath(sourceRoot),
      }),
      react(),
      viteSingleFile(),
    ],
    build: {
      write: false,
      emptyOutDir: false,
      copyPublicDir: false,
      rollupOptions: {
        input: virtualHtmlId,
      },
    },
  });
  return {
    html: extractHtml(buildResult),
    manifest: WIDGET_RENDER_MANIFEST,
  };
}

export async function buildWidgetHtml(projectRoot: string, sourceRoot: string, widgetPath: string): Promise<string> {
  return (await buildWidget(projectRoot, sourceRoot, widgetPath)).html;
}
