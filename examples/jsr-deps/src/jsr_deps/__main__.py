from typing import Final

from belgie import Environment, Runtime, Script

SOURCE: Final[str] = """
import { join } from "std_path";

export default function run() {
  return join.name;
}
"""


def resolve_join_export() -> str:
    with Environment({"std_path": "jsr:@std/path@^1"}) as env:
        env.install()
        with Runtime(env=env) as runtime:
            return str(runtime(Script(SOURCE))())


def main() -> None:
    print(resolve_join_export())  # noqa: T201


if __name__ == "__main__":
    main()
