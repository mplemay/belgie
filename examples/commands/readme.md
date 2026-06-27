# Commands

Installs an npm package into an `Environment`, then invokes its CLI binary through `Command`. Arguments are passed
directly — no shell parsing and no external Deno on PATH.

## What's happening

`Environment` pins `vite` to a version and installs it into isolated temporary state. `Command` runs the package binary
through the runtime:

```python
async with Environment({"vite": "6"}) as env:
    await env.install()
    async with Runtime(env=env) as runtime:
        await runtime(Command("vite"))("--version")
```

## Output

```text
vite/6.x.x
```

(Exact patch version depends on what `install()` resolves.)

## Run

```bash
uv run main
```
