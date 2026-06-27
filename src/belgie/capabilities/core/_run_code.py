from __future__ import annotations

from typing import TYPE_CHECKING, Annotated, Any, Final, TypedDict

from pydantic import Field, TypeAdapter

if TYPE_CHECKING:
    from belgie.capabilities.core._options import BelgieOptions


class RunCodeArguments(TypedDict):
    code: Annotated[str, Field(description="The JavaScript or TypeScript belgie.Script module source to execute.")]


RUN_CODE_TOOL_NAME: Final[str] = "run_code"
LOAD_BELGIE_TOOL_NAME: Final[str] = "load_belgie"
RUN_CODE_ADAPTER: Final[TypeAdapter[RunCodeArguments]] = TypeAdapter(RunCodeArguments)
RUN_CODE_JSON_SCHEMA: Final[dict[str, Any]] = RUN_CODE_ADAPTER.json_schema()
RUN_CODE_METADATA: Final[dict[str, str]] = {
    "code_arg_name": "code",
    "code_arg_language": "typescript",
}
RUN_CODE_DESCRIPTION: Final[str] = """\
Write and run a belgie.Script module in a sandbox.

The code is complete JavaScript or TypeScript module source for Belgie's embedded Deno-powered \
runtime. Belgie treats inline source as TypeScript, so type annotations are supported and plain \
JavaScript is valid. Export a callable function; prefer `export default async function run() { ... }`, \
or use `export function run() { ... }`.

This is a Deno environment, not Node.js. Use Deno-style imports such as `npm:pkg@version`, \
`jsr:@scope/pkg@version`, or full URLs. `await fetch(...)` is available when this capability uses \
its default runtime configuration.

Important restrictions:
- External agent tools are not available inside the sandbox.
- Return values must be JSON-serializable.
- Use `return` from the exported function for the value you want to send back.

Examples:

```typescript
export default async function run(): Promise<number[]> {
  const response = await fetch("https://hacker-news.firebaseio.com/v0/topstories.json");
  const ids: number[] = await response.json();
  return ids.slice(0, 20);
}
```
"""

DEFAULT_RUN_CODE_INSTRUCTIONS: Final[str] = RUN_CODE_DESCRIPTION
SCRIPT_TIMEOUT_MESSAGE: Final[str] = "Belgie script execution timed out after {timeout} seconds."
DEFAULT_BELGIE_CAPABILITY_ID: Final[str] = "belgie"
DEFAULT_BELGIE_CAPABILITY_DESCRIPTION: Final[str] = (
    "Execute JavaScript or TypeScript belgie.Script modules in a Deno sandbox via run_code."
)


def resolved_description(options: BelgieOptions) -> str:
    if options.dangerously_replace_instructions is not None:
        return options.dangerously_replace_instructions
    if options.instructions is None:
        return RUN_CODE_DESCRIPTION
    return f"{RUN_CODE_DESCRIPTION}\n\n{options.instructions}"
