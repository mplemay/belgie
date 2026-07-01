#!/usr/bin/env python3
"""Sync release version across pyproject.toml, Cargo.toml, Cargo.lock, and uv.lock."""

from __future__ import annotations

import os
import re
import tomllib
from pathlib import Path


def replace_version_in_named_block(path: str, header_pattern: str, name: str, version: str) -> None:
    file_path = Path(path)
    text = file_path.read_text()
    header = re.search(header_pattern, text, flags=re.MULTILINE)
    if header is None:
        raise SystemExit(f"{path} is missing block for {name}")

    next_block = re.search(r"\n(?:\[\[package\]\]|\[[^\]\n]+\])", text[header.end() :])
    block_end = len(text) if next_block is None else header.end() + next_block.start()
    block = text[header.start() : block_end]
    updated_block, count = re.subn(
        r'(?m)^version = "[^"]+"$',
        f'version = "{version}"',
        block,
        count=1,
    )
    if count != 1:
        raise SystemExit(f"{path} block for {name} is missing exactly one version")

    file_path.write_text(text[: header.start()] + updated_block + text[block_end:])


def main() -> None:
    version = os.environ["VERSION"]

    replace_version_in_named_block(
        "Cargo.toml",
        r'(?m)^\[package\]\nname = "belgie"$',
        "belgie",
        version,
    )
    replace_version_in_named_block(
        "Cargo.lock",
        r'(?ms)^\[\[package\]\]\nname = "belgie"$',
        "belgie",
        version,
    )
    replace_version_in_named_block(
        "uv.lock",
        r'(?ms)^\[\[package\]\]\nname = "belgie"$',
        "belgie",
        version,
    )

    pyproject = tomllib.loads(Path("pyproject.toml").read_text())
    cargo = tomllib.loads(Path("Cargo.toml").read_text())
    cargo_lock = tomllib.loads(Path("Cargo.lock").read_text())
    uv_lock = tomllib.loads(Path("uv.lock").read_text())

    actual = {
        "pyproject.toml": pyproject["project"]["version"],
        "Cargo.toml": cargo["package"]["version"],
    }
    for package in cargo_lock["package"]:
        if package["name"] == "belgie":
            actual["Cargo.lock"] = package["version"]
            break
    for package in uv_lock["package"]:
        if package["name"] == "belgie":
            actual["uv.lock"] = package["version"]
            break

    missing = {"Cargo.lock", "uv.lock"} - actual.keys()
    if missing:
        raise SystemExit(f"missing belgie package entries: {sorted(missing)}")

    mismatched = {name: found for name, found in actual.items() if found != version}
    if mismatched:
        raise SystemExit(f"release version mismatch: {mismatched}")


if __name__ == "__main__":
    main()
