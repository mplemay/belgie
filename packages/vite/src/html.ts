export interface WidgetHtmlDocumentOptions {
  inlineScript?: string;
  inlineStyles?: string[];
  scripts?: string[];
  styles?: string[];
}

interface BuildAsset {
  fileName: string;
  source: string | Uint8Array;
  type: "asset";
}

interface BuildChunk {
  code: string;
  dynamicImports: string[];
  fileName: string;
  imports: string[];
  isEntry: boolean;
  type: "chunk";
  viteMetadata?: { importedCss?: Set<string> };
}

export type BuildArtifact = BuildAsset | BuildChunk;

const TEXT_DECODER = new TextDecoder();

export function escapeInlineScript(value: string): string {
  return value.replaceAll(/<\/script/gi, String.raw`<\/script`);
}

export function escapeInlineStyle(value: string): string {
  return value.replaceAll(/<\/style/gi, String.raw`<\/style`);
}

export function buildVirtualEntry(widgetFilePath: string): string {
  const normalized = widgetFilePath.replaceAll("\\", "/");
  return [
    `import { createRoot } from "react-dom/client";`,
    `import { createElement, StrictMode } from "react";`,
    `import Widget from ${JSON.stringify(normalized)};`,
    "",
    `const element = document.querySelector("#root");`,
    `if (!(element instanceof HTMLElement)) {`,
    `  throw new Error("Widget root #root was not found");`,
    `}`,
    `createRoot(element).render(createElement(StrictMode, null, createElement(Widget)));`,
    "",
  ].join("\n");
}

export function renderWidgetHtmlDocument(options: WidgetHtmlDocumentOptions): string {
  const head = [
    '<meta charset="utf-8" />',
    '<meta name="viewport" content="width=device-width, initial-scale=1" />',
    ...(options.styles ?? []).map((href) => `<link rel="stylesheet" crossorigin href="${href}">`),
    ...(options.inlineStyles ?? []).map((style) => `<style>${escapeInlineStyle(style)}</style>`),
  ];
  const scripts = [
    ...(options.scripts ?? []).map((src) => `<script type="module" crossorigin src="${src}"></script>`),
    ...(options.inlineScript === undefined
      ? []
      : [`<script type="module">${escapeInlineScript(options.inlineScript)}</script>`]),
  ];
  return [
    "<!doctype html>",
    "<html>",
    "<head>",
    ...head,
    "</head>",
    "<body>",
    '<div id="root"></div>',
    ...scripts,
    "</body>",
    "</html>",
    "",
  ].join("\n");
}

function readAsset(asset: BuildAsset): string {
  return typeof asset.source === "string" ? asset.source : TEXT_DECODER.decode(asset.source);
}

export function renderBundle(bundle: Record<string, BuildArtifact | object>): string {
  const artifacts = Object.values(bundle) as BuildArtifact[];
  const chunks = artifacts.filter((artifact): artifact is BuildChunk => artifact.type === "chunk");
  const entries = chunks.filter((chunk) => chunk.isEntry);
  if (entries.length !== 1) {
    throw new Error(`@belgie/vite: expected one entry chunk, received ${entries.length}`);
  }

  const [entry] = entries;
  if (entry === undefined) {
    throw new Error("@belgie/vite: expected one entry chunk, received 0");
  }
  const extraChunks = chunks.filter((chunk) => chunk !== entry);
  if (extraChunks.length > 0) {
    throw new Error(
      `@belgie/vite: build emitted extra chunks: ${extraChunks.map((chunk) => chunk.fileName).join(", ")}`,
    );
  }

  const retainedImports = [...entry.imports, ...entry.dynamicImports].filter((item) => item !== entry.fileName);
  if (retainedImports.length > 0) {
    throw new Error(`@belgie/vite: build retained imports: ${retainedImports.join(", ")}`);
  }

  const assets = artifacts.filter((artifact): artifact is BuildAsset => artifact.type === "asset");
  const nonCssAssets = assets.filter((asset) => !asset.fileName.endsWith(".css"));
  if (nonCssAssets.length > 0) {
    throw new Error(
      `@belgie/vite: build emitted non-CSS assets: ${nonCssAssets.map((asset) => asset.fileName).join(", ")}`,
    );
  }

  const assetsByName = new Map(assets.map((asset) => [asset.fileName, asset]));
  const importedCss = [...(entry.viteMetadata?.importedCss ?? [])];
  const cssNames = importedCss.length > 0 ? importedCss : assets.map((asset) => asset.fileName).toSorted();
  const styles = cssNames.map((name) => {
    const asset = assetsByName.get(name);
    if (asset === undefined) {
      throw new Error(`@belgie/vite: build references missing CSS asset ${name}`);
    }
    return readAsset(asset);
  });
  return renderWidgetHtmlDocument({ inlineScript: entry.code, inlineStyles: styles });
}
