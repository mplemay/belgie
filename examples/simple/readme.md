# Simple

The smallest copyable belgie project. It loads a TypeScript file from disk, runs it in an async `Runtime`, and
round-trips JSON between Python and JavaScript. Use this as the baseline when adding belgie to a new repository.

## Run

```bash
uv run main
```

## What's happening

`greet.ts` exports a default `run` function — the contract belgie expects for every script module:

```typescript
export default function run(input: { name: string }): { greeting: string } {
  return { greeting: `Hello, ${input.name}!` };
}
```

Python loads the file, opens a runtime scoped to the project root, and calls `run` with keyword arguments (mapped to the
input object):

```python
script = Script.from_file(PACKAGE_DIR / "greet.ts")
async with Runtime.from_folder(PROJECT_ROOT) as runtime:
    result = await runtime(script)(name=name)
return str(result["greeting"])
```

`Runtime.from_folder(PROJECT_ROOT)` sets the working directory for `./` imports in inline scripts; here it scopes the
example package.

## Output

```text
Hello, belgie!
```
