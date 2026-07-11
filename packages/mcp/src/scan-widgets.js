import { globSync, readFileSync } from "node:fs";
import { basename, dirname, parse, resolve } from "node:path";

import { hasDefaultExport } from "./validate-widget.js";

export function scanWidgetsSync(srcDir) {
  const flatPattern = resolve(srcDir, "*.{tsx,jsx}");
  const dirPattern = resolve(srcDir, "*/index.{tsx,jsx}");

  const flatFiles = globSync(flatPattern).map((file) => ({
    name: parse(file).name,
    filePath: file,
  }));

  const dirFiles = globSync(dirPattern).map((file) => ({
    name: basename(dirname(file)),
    filePath: file,
  }));

  const candidates = [...flatFiles, ...dirFiles].filter((widget) => widget.name !== "index");

  const valid = [];
  const invalid = [];
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

export function assertUniqueWidgetNames(widgets) {
  const nameMap = new Map();
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

export function discoverWidgetsSync(srcDir) {
  const { valid } = scanWidgetsSync(srcDir);
  assertUniqueWidgetNames(valid);
  return valid;
}
