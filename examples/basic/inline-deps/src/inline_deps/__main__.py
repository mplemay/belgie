from typing import Final, cast

from belgie import Runtime, Script

SOURCE: Final[str] = """
import { assertEquals } from "jsr:@std/assert@^1";
import camelcase from "npm:camelcase@8.0.0";
import { join } from "https://deno.land/std@0.224.0/path/mod.ts";

export default function run(value) {
  assertEquals(camelcase(value), "inlineDeps");
  return {
    assertion: assertEquals.name,
    camelcase: camelcase(value),
    join: join.name,
  };
}
"""


def resolve_inline_dependencies() -> dict[str, object]:
    with Runtime() as runtime:
        return cast("dict[str, object]", runtime(Script(SOURCE))("inline-deps"))


def main() -> None:
    print(resolve_inline_dependencies())  # noqa: T201


if __name__ == "__main__":
    main()
