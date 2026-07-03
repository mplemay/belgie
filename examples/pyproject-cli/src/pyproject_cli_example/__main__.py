from pathlib import Path
from typing import Final

from belgie import Runtime, Script
from belgie.cli._operations import create_environment
from belgie.cli._project import discover_project

PROJECT_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
SOURCE: Final[str] = """
import { join } from "std_path";

export default function run() {
  return join.name;
}
"""


def resolve_join_export() -> str:
    project = discover_project(project=PROJECT_ROOT)
    with create_environment(project, frozen=False) as env:
        env.install()
        with Runtime(env=env) as runtime:
            return str(runtime(Script(SOURCE))())


def main() -> None:
    print(resolve_join_export())  # noqa: T201


if __name__ == "__main__":
    main()
