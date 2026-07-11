import { loadWidgetManifest, type WidgetManifest } from "./src/manifest.ts";

export default function run(projectRoot: string, baseUrl: string): WidgetManifest {
  return loadWidgetManifest(projectRoot, baseUrl);
}
