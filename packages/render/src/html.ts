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
  return value.replace(/<\/script/giu, String.raw`<\/script`);
}

export function escapeInlineStyle(value: string): string {
  return value.replace(/<\/style/giu, String.raw`<\/style`);
}

export function renderHtmlDocument(script: string, styles: string[]): string {
  return [
    "<!doctype html>",
    "<html>",
    "<head>",
    '<meta charset="utf-8" />',
    '<meta name="viewport" content="width=device-width, initial-scale=1" />',
    ...styles.map((style) => `<style>${escapeInlineStyle(style)}</style>`),
    "</head>",
    "<body>",
    '<div id="root"></div>',
    `<script type="module">${escapeInlineScript(script)}</script>`,
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
    throw new Error(`@belgie/render: expected one entry chunk, received ${entries.length}`);
  }

  const [entry] = entries;
  if (entry === undefined) {
    throw new Error("@belgie/render: expected one entry chunk, received 0");
  }
  const extraChunks = chunks.filter((chunk) => chunk !== entry);
  if (extraChunks.length > 0) {
    throw new Error(
      `@belgie/render: build emitted extra chunks: ${extraChunks.map((chunk) => chunk.fileName).join(", ")}`,
    );
  }

  const retainedImports = [...entry.imports, ...entry.dynamicImports].filter((item) => item !== entry.fileName);
  if (retainedImports.length > 0) {
    throw new Error(`@belgie/render: build retained imports: ${retainedImports.join(", ")}`);
  }

  const assets = artifacts.filter((artifact): artifact is BuildAsset => artifact.type === "asset");
  const nonCssAssets = assets.filter((asset) => !asset.fileName.endsWith(".css"));
  if (nonCssAssets.length > 0) {
    throw new Error(
      `@belgie/render: build emitted non-CSS assets: ${nonCssAssets.map((asset) => asset.fileName).join(", ")}`,
    );
  }

  const assetsByName = new Map(assets.map((asset) => [asset.fileName, asset]));
  const importedCss = [...(entry.viteMetadata?.importedCss ?? [])];
  const cssNames = importedCss.length > 0 ? importedCss : assets.map((asset) => asset.fileName).toSorted();
  const styles = cssNames.map((name) => {
    const asset = assetsByName.get(name);
    if (asset === undefined) {
      throw new Error(`@belgie/render: build references missing CSS asset ${name}`);
    }
    return readAsset(asset);
  });
  return renderHtmlDocument(entry.code, styles);
}
