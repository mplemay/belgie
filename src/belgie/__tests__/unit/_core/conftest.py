from __future__ import annotations

from dataclasses import dataclass
from os import PathLike
from typing import Final

from belgie import Runtime, Script

EMPTY_DENO_LOCK: Final[str] = '{"version":"5"}\n'


@dataclass(slots=True, frozen=True)
class StringPath(PathLike[str]):
    value: str

    def __fspath__(self) -> str:
        return self.value


def run_source(source: str, *args: object, **kwargs: object) -> object:
    with Runtime() as runtime:
        return runtime(Script(source))(*args, **kwargs)
