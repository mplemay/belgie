from __future__ import annotations

from pathlib import Path

import pytest

from belgie._child_process import parse_run_args


def test_parse_run_args_splits_deno_flags_module_and_arguments() -> None:
    module, argv = parse_run_args(
        [
            "run",
            "-A",
            "--unstable-node-globals",
            "--v8-flags=--expose-gc",
            "/packages/tinypool/entry/process.js",
            "worker-argument",
        ],
    )

    assert module == Path("/packages/tinypool/entry/process.js")
    assert argv == ["worker-argument"]


def test_parse_run_args_skips_separate_option_values() -> None:
    module, argv = parse_run_args(
        [
            "run",
            "--config",
            "deno.json",
            "--seed",
            "42",
            "child.js",
            "--child-flag",
        ],
    )

    assert module == Path("child.js")
    assert argv == ["--child-flag"]


@pytest.mark.parametrize("args", [[], ["eval", "1 + 1"], ["run", "-A"]])
def test_parse_run_args_rejects_missing_run_module(args: list[str]) -> None:
    with pytest.raises(ValueError, match="child runtime"):
        parse_run_args(args)
