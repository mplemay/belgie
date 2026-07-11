export function escapeInlineScript(value: string): string {
  return value.replace(/<\/script/gi, "<\\/script");
}

export function escapeInlineStyle(value: string): string {
  return value.replace(/<\/style/gi, "<\\/style");
}

export function renderDocument(options: {
  inlineScript?: string;
  styles?: string[];
}): string {
  const head = [
    '<meta charset="utf-8" />',
    ...(options.styles ?? []).map((style) => `<style>${escapeInlineStyle(style)}</style>`),
  ];
  const scripts = options.inlineScript
    ? [`<script type="module">${escapeInlineScript(options.inlineScript)}</script>`]
    : [];
  return `<!doctype html>\n<html>\n<head>\n${head.join("\n")}\n</head>\n<body>\n<div id="root"></div>\n${scripts.join("\n")}\n</body>\n</html>\n`;
}

export function renderWidgetBootstrap(widgetEntryId: string): string {
  return `import widget from ${JSON.stringify(widgetEntryId)};\n\nwidget();\n`;
}
