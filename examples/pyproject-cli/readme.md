# Pyproject CLI Example

This example declares Belgie package dependencies in `pyproject.toml`:

```toml
[tool.belgie.dependencies]
std_path = "jsr:@std/path@^1"
```

Use the optional CLI extra to inspect, add, lock, and install those dependencies:

```bash
uv run belgie list
uv run belgie add is-number npm:is-number@7.0.0
uv run belgie lock
uv run belgie install
uv run main
```

`uv run main` loads the same `[tool.belgie.dependencies]` table, creates a Belgie `Environment`, and imports
`std_path` from TypeScript.
