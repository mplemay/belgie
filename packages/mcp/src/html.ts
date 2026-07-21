export interface WidgetHtmlDocumentOptions {
  inlineScript?: string;
  inlineStyles?: string[];
  scripts?: string[];
  styles?: string[];
}

export function escapeInlineScript(value: string): string {
  return value.replaceAll(/<\/script/gi, String.raw`<\/script`);
}

export function escapeInlineStyle(value: string): string {
  return value.replaceAll(/<\/style/gi, String.raw`<\/style`);
}

export function buildVirtualEntry(widgetFilePath: string): string {
  const normalized = widgetFilePath.replaceAll("\\", "/");
  return [
    `import { mountWidget } from "@belgie/mcp";`,
    `import Widget from ${JSON.stringify(normalized)};`,
    "",
    "mountWidget(Widget);",
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
