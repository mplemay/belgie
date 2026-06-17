from pathlib import Path

from belgie import Runtime, Script
from belgie.dependencies import lock

PROJECT_ROOT = Path(__file__).resolve().parents[2]

SOURCE = """
import { join } from "std_path";

export default function run() {
  return join.name;
}
"""


def resolve_join_export() -> str:
    lock(cwd=PROJECT_ROOT)
    with Runtime(cwd=PROJECT_ROOT)(Script(SOURCE)) as run:
        return str(run())


def main() -> None:
    print(resolve_join_export())  # noqa: T201


if __name__ == "__main__":
    main()
