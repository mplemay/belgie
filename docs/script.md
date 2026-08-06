# Script

Use `Script` to give a [`Runtime`](runtime.md) executable JavaScript, TypeScript, or TSX source.
Choose inline source for a short transform or agent-authored module. Choose a file when the script
belongs to your project and needs local imports.

A script is reusable. The runtime creates its callable runner when you pass it to `runtime(script)`.

## Inline source

Inline source is useful for short transforms and scripts whose contents come from configuration or
an agent:

```python
from belgie import Runtime, Script

script = Script("""
export default function run(value: string): string {
  return value.trim().toUpperCase();
}
""")

with Runtime() as runtime:
    result = runtime(script)(" belgie ")
```

The source is parsed as a module. Export a callable function, preferably a default `run` function,
and return the value that Python should receive. The runner passes positional and keyword arguments
to that function.

## File-based source

Use `Script.from_file()` when the module belongs to your project:

```python
from pathlib import Path

from belgie import Runtime, Script

script = Script.from_file(Path("src/scripts/transform.ts"))

with Runtime.from_folder(".") as runtime:
    result = runtime(script)(value="hello")
```

The filename is retained by the script and helps relative imports resolve from the expected module
location. Use a project-rooted [`Runtime.from_folder()`](runtime.md) when the file imports other
local modules.

## Arguments and return values

Script arguments and results use Belgie's JSON bridge.

| Python value | JavaScript value |
| --- | --- |
| `None` | `null` |
| `bool` | boolean |
| `int` or `float` | number |
| `str` | string |
| `list` or `tuple` | array |
| `dict[str, ...]` | object |

Dates, class instances, functions, streams, and other non-JSON values must be converted inside the
script before they cross back to Python. For agent integrations, this same rule applies to the
value returned by an agent's JavaScript sandbox tool.

## Imports

Use Deno-style specifiers in source code:

```typescript
import camelcase from "npm:camelcase@8.0.0";
import { join } from "jsr:@std/path@^1";
import { assertEquals } from "https://deno.land/std@0.224.0/assert/mod.ts";
```

For repeatable project dependencies, declare aliases in an [`Environment`](environment.md) instead
of repeating versioned specifiers throughout scripts.

## Errors and cancellation

Script failures are raised as Belgie runtime errors. If the operation is asynchronous, cancellation
propagates through the awaiting Python task. Keep long-running scripts bounded with application
timeouts or the agent integration's `timeout` option.

## See also

- [Runtime](runtime.md)
- [Environment](environment.md)
- [Inline rendering with `@belgie/vite`](packages/vite.md)
