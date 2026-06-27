# Environment

Declares JSR dependencies through `Environment`, like [jsr-deps](../jsr-deps), and also shows sync and async context
managers plus a persistent working directory via `path=`. Temporary Deno state is removed when the environment exits;
files written under `path` remain on disk.

## Run

```bash
uv run main
```

## What's happening

Sync usage — enter the environment, install, then run the script:

```python
with Environment({"std_path": "jsr:@std/path@^1"}) as env:
    env.install()
    with Runtime(env=env) as runtime:
        result = runtime(Script(SOURCE))()
```

Async with a persistent cwd — `path=Path.cwd()` keeps the working directory across the environment lifetime:

```python
async with Environment({"std_path": "jsr:@std/path@^1"}, path=Path.cwd()) as env:
    await env.install()
    async with Runtime(env=env) as runtime:
        result = await runtime(Script(SOURCE))()
```

The script imports `join` from the `std_path` alias, same as in [jsr-deps](../jsr-deps).

## Output

```text
join
```
