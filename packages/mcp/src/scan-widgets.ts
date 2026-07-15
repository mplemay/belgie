import { globSync, readFileSync } from "node:fs";
import { basename, dirname, resolve } from "node:path";

import { hasDefaultExport } from "./validate-widget.js";

export type WidgetCandidate = {
  name: string;
  filePath: string;
};

export type InvalidWidget = {
  filePath: string;
};

export type WidgetScanResult = {
  valid: WidgetCandidate[];
  invalid: InvalidWidget[];
};

export function scanWidgetsSync(srcDir: string): WidgetScanResult {
  const pattern = resolve(srcDir, "*/widget.tsx");
  const candidates = globSync(pattern).map((file) => ({
    name: basename(dirname(file)),
    filePath: file,
  }));

  const valid: WidgetCandidate[] = [];
  const invalid: InvalidWidget[] = [];
  for (const candidate of candidates) {
    const code = readFileSync(candidate.filePath, "utf-8");
    if (hasDefaultExport(code)) {
      valid.push(candidate);
    } else {
      invalid.push({ filePath: candidate.filePath });
    }
  }

  return { valid, invalid };
}

export function assertUniqueWidgetNames(widgets: WidgetCandidate[]): void {
  const nameMap = new Map<string, string[]>();
  for (const widget of widgets) {
    const paths = nameMap.get(widget.name) ?? [];
    paths.push(widget.filePath);
    nameMap.set(widget.name, paths);
  }

  for (const [name, paths] of nameMap) {
    if (paths.length > 1) {
      throw new Error(
        `belgie: duplicate widget name "${name}" resolved from:\n  - ${paths.join("\n  - ")}\nRename one of the files to avoid the conflict.`,
      );
    }
  }
}

export function assertNoInvalidWidgets(invalid: InvalidWidget[]): void {
  if (invalid.length === 0) {
    return;
  }
  const paths = invalid.map((widget) => widget.filePath).join("\n  - ");
  throw new Error(
    `belgie: widget file(s) missing a default export:\n  - ${paths}\nAdd a default export so the widget can be built.`,
  );
}

export function discoverWidgetsSync(srcDir: string): WidgetCandidate[] {
  const { valid } = scanWidgetsSync(srcDir);
  assertUniqueWidgetNames(valid);
  return valid;
}
