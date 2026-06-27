# Inline deps

Imports `npm:`, `jsr:`, and URL modules directly inside a `Script` string — no `Environment` or lockfile required. Use
this when dependencies are declared in JavaScript rather than in Python.

## What's happening

The script embeds Deno-style inline imports and exports a `run` function:

```python
SOURCE = """
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

with Runtime() as runtime:
    result = runtime(Script(SOURCE))("inline-deps")
```

Belgie resolves and caches each import when the script runs. For a Python-owned dependency map or lockfile, see
`jsr-deps` or `environment`.

## Output

```text
{'assertion': 'assertEquals', 'camelcase': 'inlineDeps', 'join': 'join'}
```

## Run

```bash
uv run main
```
