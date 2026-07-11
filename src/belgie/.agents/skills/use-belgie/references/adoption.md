# Adoption

Use this file when the task is to make belgie work cleanly in another repository.

## Recommended bootstrap

```bash
uv add belgie
```

## Compatibility

- Python: `>=3.12,<3.15`
- Runtime Python dependencies: none
- Node.js, Deno, and npm are **not** required on `PATH`

## Minimum external-repo structure

Inline script only:

```text
my-app/
├── pyproject.toml
└── main.py
```

TypeScript files with relative imports:

```text
my-app/
├── pyproject.toml
├── main.py
└── scripts/
    ├── transform.ts
    └── lib/
        └── helpers.ts
```

Isolated JS dependencies:

```text
my-app/
├── pyproject.toml
└── main.py
```

MCP Apps with React widgets:

```text
my-mcp-app/
├── pyproject.toml
├── vite.config.ts
├── deno.lock
└── src/
    ├── widgets/
    │   └── get-time/
    │       └── index.tsx
    └── mcp_app/
        └── __main__.py
```

```toml
[tool.belgie.dependencies]
"@belgie/mcp" = "file:path/to/packages/mcp"
react = "npm:react@^19"
vite = "npm:vite@6.1.0"
"@vitejs/plugin-react" = "npm:@vitejs/plugin-react@^4"
```

Declare `@belgie/mcp` as a `file:` dependency pointing at the local `@belgie/mcp` package. Add `belgie()` to
`vite.config.ts`, run `vite build`, then serve `dist` (for example with FastAPI `app.frontend()`).

JavaScript packages for scripts belong in `Environment({...})` or `[tool.belgie.dependencies]`, not in Python
`[project.dependencies]`.

## Python dependency baseline

```toml
[project]
requires-python = ">=3.12,<3.15"
dependencies = [
    "belgie",
]
```

## Public API checklist

Before finishing adoption, confirm:

- [ ] `Environment` and `Runtime` are used as context managers (`with` / `async with`)
- [ ] Script packages use direct `npm:` / `jsr:` / URL imports, or `env.install()` runs for aliases and commands
- [ ] MCP projects declare `[tool.belgie.dependencies]`, use `belgie()` in `vite.config.ts`, and run
      `belgie lock` / `belgie install` before `vite build`
- [ ] JS modules export a callable (`export default function run(...)` or `export default () => ...`)
- [ ] Python ↔ JS data is JSON-serializable (dicts, lists, primitives)
- [ ] Errors are imported from `belgie.errors`
- [ ] `Runtime.from_folder()` is used only for relative import roots, not package management
- [ ] `Command` args are separate `str` values, not shell strings

## Verification steps

1. Import succeeds: `from belgie import Runtime, Script`
2. Inline script returns expected value inside `with Runtime() as run:`
3. If using `Environment`, `install()` completes without error
4. If using `Script.from_file`, `Runtime.from_folder` points at the import root
5. If using `Command`, the binary runs and returns `None` on success

For quick copy-paste setups, see [quickstart.md](quickstart.md).
