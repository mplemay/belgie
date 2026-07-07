import packageJson from "../package.json" with { type: "json" };

export type WidgetRenderManifest = {
  renderPackageName: string;
  renderPackageVersion: string;
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
  renderPackageName: packageString(widgetPackage.name, "@belgie/widget"),
  renderPackageVersion: packageString(widgetPackage.version, "0.0.0"),
};
