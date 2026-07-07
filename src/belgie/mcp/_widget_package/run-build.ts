import { buildWidgetHtml } from "./src/build.ts";

export default async function run(projectRoot: string, sourceRoot: string, widgetPath: string): Promise<string> {
  return await buildWidgetHtml(projectRoot, sourceRoot, widgetPath);
}
