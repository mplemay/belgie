from __future__ import annotations

import json
from pathlib import Path


def write_local_package_with_bin(
    root: Path,
    *,
    name: str = "local-pkg",
    bin_script: str = 'import { writeFileSync } from "node:fs"; writeFileSync("local-command.txt", "ok\\n");\n',
    bin_name: str | None = None,
) -> Path:
    package = root / name
    package.mkdir(parents=True, exist_ok=True)
    package_json: dict[str, object] = {
        "name": name,
        "version": "1.0.0",
        "type": "module",
        "exports": "./index.js",
    }
    if bin_name is not None:
        package_json["bin"] = {bin_name: "./bin.js"}
    (package / "package.json").write_text(
        json.dumps(package_json, indent=2) + "\n",
        encoding="utf-8",
    )
    (package / "index.js").write_text("export const answer = 42;\n", encoding="utf-8")
    if bin_name is not None:
        (package / "bin.js").write_text(bin_script, encoding="utf-8")
    return package
