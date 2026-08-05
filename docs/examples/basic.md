# Basic Runtime examples

These examples show the direct Python-to-Deno path. Start with an inline or file-based script, then
add shared dependencies, a workspace, or an installed command as the project grows.

## File-based scripts

The `simple` example keeps a TypeScript module next to the Python package and runs it from a
folder-backed runtime. The complete entrypoint comes from the shipped example:

```python
--8<-- "examples/basic/simple/src/simple/__main__.py"
```

See [`examples/basic/simple`](https://github.com/mplemay/belgie/tree/main/examples/basic/simple)
for the complete project.

## Inline dependencies

Inline modules can import npm, JSR, and URL modules directly:

```typescript
import camelcase from "npm:camelcase@8.0.0";
import { join } from "https://deno.land/std@0.224.0/path/mod.ts";

export default function run(value: string) {
  return {
    camelcase: camelcase(value),
    join: join.name,
  };
}
```

Use this path for a small script whose dependencies do not need to be shared. Use an
[`Environment`](../environment.md) when the project needs one dependency set and lockfile across
runs.

## Named environment dependencies

The `jsr-deps` example declares an alias and imports it by name. Its complete entrypoint is:

```python
--8<-- "examples/basic/jsr-deps/src/jsr_deps/__main__.py"
```

This keeps dependency declarations and lockfile updates separate from script source.

## Commands

The `commands` example installs Vite and invokes its binary from Python. Its complete entrypoint is:

```python
--8<-- "examples/basic/commands/src/commands_example/__main__.py"
```

See [Command](../command.md) for working directories, environment variables, and module mode.

## Run the examples

```bash
cd examples/basic/simple
uv run main

cd ../inline-deps
uv run main

cd ../commands
uv run main
```

## See also

- [Runtime](../runtime.md)
- [Script](../script.md)
- [Environment](../environment.md)
- [Command](../command.md)
