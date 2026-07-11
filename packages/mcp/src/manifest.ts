import packageJson from "../package.json" with { type: "json" };

export type WidgetRenderManifest = {
  packageName: string;
  packageVersion: string;
};

type PackageJson = {
  name?: unknown;
  version?: unknown;
};

function packageString(value: unknown, fallback: string): string {
  return typeof value === "string" && value.length > 0 ? value : fallback;
}

const widgetPackage = packageJson as PackageJson;

export const WIDGET_RENDER_MANIFEST: WidgetRenderManifest = {
  packageName: packageString(widgetPackage.name, "@belgie/mcp"),
  packageVersion: packageString(widgetPackage.version, "0.0.0"),
};
