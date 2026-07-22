import { renderWidgetHtmlDocument } from "./html.js";

const TEXT_DECODER = new TextDecoder();

export interface BuildAsset {
  fileName: string;
  source: string | Uint8Array;
  type: "asset";
}

export interface BuildChunk {
  code: string;
  dynamicImports: string[];
  facadeModuleId: string | null;
  fileName: string;
  imports: string[];
  isEntry: boolean;
  type: "chunk";
  viteMetadata?: { importedCss?: Set<string> };
}

export type BuildArtifact = BuildAsset | BuildChunk;

function readAsset(asset: BuildAsset): string {
  return typeof asset.source === "string" ? asset.source : TEXT_DECODER.decode(asset.source);
}

export function renderWidgetBundle(name: string, bundle: Record<string, BuildArtifact> | BuildArtifact[]): string {
  const artifacts = Array.isArray(bundle) ? bundle : Object.values(bundle);
  const chunks = artifacts.filter((artifact): artifact is BuildChunk => artifact.type === "chunk");
  const entries = chunks.filter((chunk) => chunk.isEntry);
  if (entries.length !== 1) {
    throw new Error(`belgie: expected one entry chunk for widget "${name}", received ${entries.length}`);
  }

  const entry = entries[0];
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
  const cssNames = importedCss.length > 0 ? importedCss : assets.map((asset) => asset.fileName).toSorted();
  const styles = cssNames.map((cssName) => {
    const asset = assetsByName.get(cssName);
    if (asset === undefined) {
      throw new Error(`belgie: widget "${name}" references missing CSS asset ${cssName}`);
    }
    return readAsset(asset);
  });
  return renderWidgetHtmlDocument({ inlineScript: entry.code, inlineStyles: styles });
}
