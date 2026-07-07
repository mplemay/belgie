import { createRequire } from "node:module";
import { join, resolve } from "node:path";
import react from "@vitejs/plugin-react";
import { build, type Plugin } from "vite";
import { viteSingleFile } from "vite-plugin-singlefile";

import { renderDocument, renderWidgetBootstrap } from "./html.ts";

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

function toVitePath(path: string): string {
  return path.replaceAll("\\", "/");
}

function resolveDependency(projectRoot: string, specifier: string): string {
  const require = createRequire(join(projectRoot, "package.json"));
  return toVitePath(require.resolve(specifier));
}

function belgieVirtualInputPlugin(options: {
  projectRoot: string;
  virtualHtmlId: string;
  widgetFileId: string;
}): Plugin {
  const widgetRuntimeId = toVitePath(
    join(options.projectRoot, "node_modules", "@belgie", "widget", "src", "index.tsx"),
  );

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
      if (id === "@belgie/widget") {
        return widgetRuntimeId;
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

export async function buildWidgetHtml(projectRoot: string, sourceRoot: string, widgetPath: string): Promise<string> {
  const normalizedProjectRoot = toVitePath(projectRoot);
  const virtualHtmlId = toVitePath(join(projectRoot, VIRTUAL_HTML_PATH));
  const widgetFileId = toVitePath(resolve(sourceRoot, widgetPath));
  const buildResult = await build({
    root: normalizedProjectRoot,
    configFile: false,
    logLevel: "error",
    resolve: {
      alias: [
        { find: /^react$/, replacement: resolveDependency(projectRoot, "react") },
        { find: /^react-dom$/, replacement: resolveDependency(projectRoot, "react-dom") },
        {
          find: /^react-dom\/client$/,
          replacement: resolveDependency(projectRoot, "react-dom/client"),
        },
        {
          find: /^react\/jsx-runtime$/,
          replacement: resolveDependency(projectRoot, "react/jsx-runtime"),
        },
      ],
      dedupe: ["react", "react-dom"],
    },
    plugins: [
      belgieVirtualInputPlugin({
        projectRoot: normalizedProjectRoot,
        virtualHtmlId,
        widgetFileId,
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
  return extractHtml(buildResult);
}
