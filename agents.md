# Agent Instructions

## Tooling

- **`uv`:** The python package manager.
  - *Usage:* `uv`
  - *Rules:*
    - **Always run `uv` with elevated permissions.**
    - **Don't use other package managers for python dependencies (ex: `pip`, `poetry`, etc.)**
- **`prek`**: Checks, linting, and formatting
  - *Usage:* `uv run prek`
  - *Files:* [configuration](prek.toml)
  - *Tools:* `rumdl` (markdown), `ruff` (linting), `ty` (type checker)
  - *Rules:*
    - **Don't run the underlying linters / formatters directly.**
    - **Never use file-wide ignores.**
    - **Never update the linter / formatter configs without explicit permission.**
- **`git`**: Version control
  - *Usage:* `git`
  - *Files:* [ignores (project)](.gitignore)
  - *Rules:*
    - **Always use all lowecase single-line conventional commit messages (ex: `feat: enable ssr in production`).**

## Conventions

### Python

- The targets python versions greater than or equal to 3.12
- Given the project targets a more modern python, use functionality such as:
  - The walrus operator (`:=`)
  - Modern type hints (`dict`)
  - Type parameters `class MyClass[T: MyParent]: ...`
  - The `Self` type for return types (`from typing import Self`)
- Type annotations:
  - **Do not** annotate `self` parameters - the type is implicit
  - Use `Self` for return types when returning the instance
  - Example: `def add_item(self, item: str) -> Self: ...` (note: no type on `self`)
- Classes and data structures:
  - Use `@dataclass` (from `dataclasses`) instead of manually defining `__init__` for data-holding classes
  - Consider using `slots=True` for memory efficiency and attribute access protection
  - Use `kw_only=True` to require keyword arguments for better readability at call sites
  - Use `frozen=True` for immutable data structures
  - Example: `@dataclass(slots=True, kw_only=True, frozen=True)`
  - **When NOT to use dataclass**:
    - Inheriting from non-dataclass parents (can cause MRO and initialization issues)
    - Need for `__new__` method (for singleton patterns, custom object creation)
    - Complex property logic with getters/setters that transform data
    - Need for `__init_subclass__` or metaclass customization
    - Classes with significant behavior/methods (prefer traditional classes for these)
  - **When to use dataclass**:
    - Simple data containers with minimal logic
    - Configuration objects, DTOs (Data Transfer Objects), result types
    - Immutable value objects (use `frozen=True`)
    - When you want automatic `__eq__`, `__repr__`, `__hash__` implementations
- Prefer importing using `from x import y` instead of `import x`
- Import local modules using the full path (ex: `from my_project.my_module import MyClass`)
- Internal compatibility module (`._core`) imports:
  - Prefer direct `from belgie._core import ...` when there is no name clash in that file.
  - When a symbol from `_core` would clash with a Python-defined name in the same module, import with a `*Impl` /
    `*_impl` alias, then assign or wrap as needed:
    - Types/classes: `FooImpl` (e.g. `from belgie._core import Foo as FooImpl`, then `Foo = FooImpl` or a thin wrapper).
    - Functions: `foo_impl` (snake_case with `_impl` suffix).
  - Do not use leading-underscore import aliases (`_Foo`, `_foo`) for this re-export pattern.
- **Don't use** docstrings, instead add inline comments only in places where there is complex or easily breakable logic
- **No file-wide suppressions** in source: do not use a first-line or module-wide pragma such as `# ruff: noqa: ...` for
  the whole file, a blanket `# type: ignore` on a module, or equivalent file-scoped pyright/bandit-style ignores.
- **Prefer fixing the cause**: adjust types or public API, or tooling configuration that matches documented conventions
  (for example `pyproject.toml`), so the diagnostic does not apply.
- **If suppression is unavoidable**, use the **smallest scope** (usually a single line) with **explicit rule codes**
  (for example `# noqa: ARG002`), not a whole-file waiver. This refers to pragmas in `.py` files, not to path-based
  rules in `pyproject.toml` (which should stay minimal and justified).
- For type aliases, prefer Python's modern syntax: `type MyAlias = SomeType` (PEP 695 style), especially in new code.
- Constants:
  - Module-level runtime constants must be public (no leading underscore), `SCREAMING_SNAKE_CASE`, and annotated with
    `Final[T]` from `typing`. This includes path-derived constants and multiline string literals, not just simple
    literals.
  - Examples:
    - `DEFAULT_HOST: Final[str] = "127.0.0.1"`
    - `PACKAGE_DIR: Final[Path] = Path(__file__).resolve().parent`
    - `PROJECT_ROOT: Final[Path] = Path(__file__).resolve().parents[2]`
  - Does not apply to type aliases (`type Foo = ...`), TypedDict assignments, class instance attributes (including those
    annotated with `Final` in `__init__`), application wiring globals (`ship`, `mcp`, etc.), or special dunders
    (`__all__`, etc.).
- URL construction:
  - Use `urllib.parse` methods for URL manipulation (don't use string concatenation or f-strings for query params)
  - Use `urlencode()` for query parameters
  - Use `urlparse()` and `urlunparse()` for URL composition
  - Example: `urlunparse((parsed.scheme, parsed.netloc, parsed.path, "", urlencode(params), ""))`
  - This ensures proper encoding and avoids common URL injection vulnerabilities

### Testing

- Test files are named `test_<module>.py` to match the source module they test (e.g. tests for `core.py` go in
  `test_core.py`, tests for `_core` go in `test__core.py`)
- Do not name test files by functionality (e.g. avoid `test_ship_init.py`, `test_template.py`)
- Tests live under `__tests__/` with `unit/` and `integration/` subdirectories. Group tests by domain in
  subfolders (`agent/`, `cli/`, `pydantic_ai/`, `langchain/`, `_core/`, etc.).
- Integration tests are marked with `@pytest.mark.integration`

## After Changes

1. `uv run pytest` (note: if anything is broken, figure out the root cause, fix it, and start again)
2. `uv run prek run --all-files` (note: if the linter fails, restart from step 1)
3. `git commit`
4. `git push`

## Cursor Cloud specific instructions

The VM snapshot already provides `uv`, Rust (stable), Node, Python 3.12, plus two things
required by the Rust build that are easy to miss:

- **`net.git-fetch-with-cli = true`** is set in the global cargo config (`$CARGO_HOME/config.toml`).
  The `_core` crate pins Deno crates from `github.com/denoland/deno` (a git dependency), and cargo
  needs the git CLI to fetch them. Without this, `uv sync` / `cargo` builds fail to resolve deps.
- **`libpython3.12-dev`** is installed. `uv sync` builds `_core` with the `extension-module` feature
  (no libpython link) and works without it, but `cargo test --package belgie --all-targets` links a
  test binary against `-lpython3.12`, which needs the unversioned `libpython3.12.so` symlink from
  the `-dev` package. If Rust tests fail with `unable to find library -lpython3.12`, reinstall it.

Startup / run notes:

- The update script runs `uv sync`, which builds the `_core` Rust extension via maturin. The first
  cold build compiles the whole embedded Deno runtime (~10 min); warm rebuilds are near-instant
  because `[tool.uv].cache-keys` in `pyproject.toml` keys the cached wheel on the Rust/Cargo sources.
  After a `uv sync` rebuild the new `.so` is picked up on the next `python`/`uv run` invocation
  (no hot reload for the compiled extension).
- **Full `uv run pytest` requires the `@belgie/mcp` npm package to be built** (MCP tests import its
  `dist/`). Build it with `cd packages/mcp && npm install && npm run build` (see `.github/workflows/test.yml`).
  This is a build step, not part of the update script; the built `dist/` persists in the snapshot,
  so rebuild only after changing `packages/mcp` sources.
- Standard commands live in the sections above and in `.github/workflows/test.yml`: Python tests
  `uv run pytest`, Rust tests `cargo test --package belgie --all-targets`, lint
  `uv run prek run --all-files`.
- Deno is bundled inside the compiled extension — no external Deno/Node runtime is needed to run the
  `belgie` library itself (Node is only used to build `@belgie/mcp`).
- API gotcha: the README quick-start shows `Script[[str], str](...)`, but the current
  `belgie._core.Script` is not subscriptable — construct scripts with `Script(...)` or
  `Script.from_file(...)` (see `examples/simple`).
