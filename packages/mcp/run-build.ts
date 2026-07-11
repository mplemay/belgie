import { buildWidget, type WidgetBuildResult } from "./src/build.ts";

export default async function run(
  projectRoot: string,
  sourceRoot: string,
  widgetPath: string,
): Promise<WidgetBuildResult> {
  return await buildWidget(projectRoot, sourceRoot, widgetPath);
}
