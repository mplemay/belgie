# Commands

Installs an npm package into an `Environment`, then invokes its CLI binary through `Command`. Arguments are passed
directly -- no shell parsing and no external Deno on PATH.

## Run

```bash
uv run main
```

## What's happening

`Environment` pins `vite` and its native `rollup` dependency to versions that are compatible with the embedded runtime,
then installs them into isolated temporary state. `Command` runs the package binary through the runtime:

Rollup stays on 4.62.2 because 4.62.3's Windows Node-API loader falls back to `libnode`, which is unavailable when Deno
is embedded in Belgie's Python extension.

```python
async with Environment({"vite": "6", "rollup": "4.62.2"}) as env:
    await env.install()
    async with Runtime(env=env) as runtime:
        await runtime(Command("vite"))("--version")
```

## Output

```text
vite/6.x.x
```

(Exact patch version depends on what `install()` resolves.)
