export type WidgetHtmlDocumentOptions = {
  scripts: string[];
  styles: string[];
};

export function buildVirtualEntry(widgetFilePath: string): string {
  const normalized = widgetFilePath.replace(/\\/g, "/");
  return [
    `import { createElement } from "react";`,
    `import { mountWidget } from "@belgie/mcp";`,
    `import Widget from ${JSON.stringify(normalized)};`,
    "",
    "mountWidget(createElement(Widget));",
    "",
  ].join("\n");
}

export function renderWidgetHtmlDocument(options: WidgetHtmlDocumentOptions): string {
  const head = [
    '<meta charset="utf-8" />',
    ...options.styles.map((href) => `<link rel="stylesheet" crossorigin href="${href}">`),
    ...options.scripts.map((src) => `<script type="module" crossorigin src="${src}"></script>`),
  ];
  return [
    "<!doctype html>",
    "<html>",
    "<head>",
    ...head,
    "</head>",
    "<body>",
    '<div id="root"></div>',
    "</body>",
    "</html>",
    "",
  ].join("\n");
}
