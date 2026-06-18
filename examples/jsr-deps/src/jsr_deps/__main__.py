from pathlib import Path
from typing import Final

from belgie import Runtime, Script
from belgie.dependencies import lock

PROJECT_ROOT: Final[Path] = Path(__file__).resolve().parents[2]

SOURCE: Final[str] = """
import { join } from "std_path";

export default function run() {
  return join.name;
}
"""


def resolve_join_export() -> str:
    lock(cwd=PROJECT_ROOT)
    with Runtime.from_folder(PROJECT_ROOT)(Script(SOURCE)) as run:
        return str(run())


def main() -> None:
    print(resolve_join_export())  # noqa: T201


if __name__ == "__main__":
    main()
