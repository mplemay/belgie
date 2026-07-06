export function escapeInlineScript(value: string): string {
  return value.replace(/<\/script/gi, "<\\/script");
}

export function escapeInlineStyle(value: string): string {
  return value.replace(/<\/style/gi, "<\\/style");
}

export function renderDocument({ script, styles }: { script: string; styles?: string[] }): string {
  const styleTags = (styles ?? []).map((style) => `<style>${escapeInlineStyle(style)}</style>`).join("");
  return (
    '<!doctype html><html><head><meta charset="utf-8">' +
    `${styleTags}</head><body><div id="root"></div>` +
    `<script type="module">${escapeInlineScript(script)}</script></body></html>\n`
  );
}
