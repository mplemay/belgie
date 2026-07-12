import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, resolve } from "node:path";

export type WidgetEntry = {
  name: string;
  html: string;
};

export type WidgetManifest = {
  baseUrl: string;
  widgets: Record<string, WidgetEntry>;
};

function toPosix(path: string): string {
  return path.replaceAll("\\", "/");
}

function normalizeBaseUrl(baseUrl: string): string {
  return baseUrl.replace(/\/+$/, "");
}

function absolutizeAssetUrls(html: string, baseUrl: string): string {
  const base = normalizeBaseUrl(baseUrl);
  return html
    .replace(/\b(src|href)=["'](\/?assets\/[^"']+)["']/g, (_match, attr: string, path: string) => {
      const normalized = path.startsWith("/") ? path : `/${path}`;
      return `${attr}="${base}${normalized}"`;
    })
    .replace(/\b(src|href)=["']\.\/assets\/([^"']+)["']/g, (_match, attr: string, path: string) => {
      return `${attr}="${base}/assets/${path}"`;
    });
}

function collectWidgetHtmlFiles(widgetsDir: string): Array<{ name: string; filePath: string }> {
  let entries: string[];
  try {
    entries = readdirSync(widgetsDir);
  } catch {
    return [];
  }

  const widgets: Array<{ name: string; filePath: string }> = [];
  for (const entry of entries) {
    const widgetDir = join(widgetsDir, entry);
    try {
      if (!statSync(widgetDir).isDirectory()) {
        continue;
      }
    } catch {
      continue;
    }
    const htmlPath = join(widgetDir, "index.html");
    try {
      if (statSync(htmlPath).isFile()) {
        widgets.push({ name: entry, filePath: htmlPath });
      }
    } catch {
      // missing index.html
    }
  }
  return widgets;
}

export function loadWidgetManifest(projectRoot: string, baseUrl: string): WidgetManifest {
  const root = resolve(projectRoot);
  const widgetsDir = join(root, "dist", "widgets");
  const discovered = collectWidgetHtmlFiles(widgetsDir);
  if (discovered.length === 0) {
    throw new Error(
      `No widget HTML found under ${toPosix(widgetsDir)}. Run vite build with the belgie() plugin first.`,
    );
  }

  const widgets: Record<string, WidgetEntry> = {};
  for (const widget of discovered) {
    const html = absolutizeAssetUrls(readFileSync(widget.filePath, "utf-8"), baseUrl);
    widgets[widget.name] = {
      name: widget.name,
      html,
    };
  }

  return {
    baseUrl: normalizeBaseUrl(baseUrl),
    widgets,
  };
}
