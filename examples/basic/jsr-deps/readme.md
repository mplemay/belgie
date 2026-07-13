# JSR deps

Python declares a JSR package under a short alias; `Environment.install()` resolves it, and the script imports by that
alias. Use this when Python owns the dependency map instead of inline `jsr:` URLs in source.

## Run

```bash
uv run main
```

## What's happening

The environment maps `std_path` to a JSR package. After `install()`, the script imports through the alias:

```python
SOURCE = """
import { join } from "std_path";

export default function run() {
  return join.name;
}
"""

with Environment({"std_path": "jsr:@std/path@^1"}) as env:
    env.install()
    with Runtime(env=env) as runtime:
        result = runtime(Script(SOURCE))()
```

Same JSR pattern as [environment](../environment), but sync-only and without a persistent working directory.

## Output

```text
join
```
