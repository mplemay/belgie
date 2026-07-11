export function buildVirtualEntry(widgetFilePath) {
  const normalized = widgetFilePath.replace(/\\/g, "/");
  return [
    `import widget from ${JSON.stringify(normalized)};`,
    "",
    "widget();",
    "",
  ].join("\n");
}

export function renderWidgetHtmlDocument(options) {
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
