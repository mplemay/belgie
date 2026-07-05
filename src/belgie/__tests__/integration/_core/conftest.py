from __future__ import annotations

from pathlib import Path

from belgie import Runtime, Script


def run_script(tmp_path: Path, source: str, input_value: object | None = None) -> object:
    with Runtime() as runtime:
        run = runtime(Script(source))
        if input_value is None:
            return run()
        return run(input_value)
