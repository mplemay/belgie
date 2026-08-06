# Contributing

Belgie combines Python bindings, Rust runtime code, TypeScript packages, examples, and published
documentation. Keep a change focused on the layer it affects and validate the user-facing path.

## Set up the repository

Use `uv` for Python dependencies:

```bash
uv sync
```

The repository targets Python 3.12 or newer within its supported range. The bundled Deno runtime
and Rust extension are built through the project's normal tooling.

## Run checks

Run the test suite and repository hooks before opening a pull request:

```bash
uv run pytest
uv run prek run --all-files
```

The hooks include Python checks, TypeScript formatting and linting through Belgie, Markdown
formatting and rumdl validation, and Rust checks for relevant changes.

For documentation changes, also build the site strictly:

```bash
uv sync --group docs --no-install-project
uv run --no-project mkdocs build --strict
```

## Documentation changes

Follow the repository's `docs/agents.md` instructions for documentation information architecture,
writing style, code examples, navigation, and validation rules. Keep that file excluded from the
published site.

Use current public imports and shipped examples. Add a page to `mkdocs.yml` when it is intended for
the site, and link to the canonical page rather than duplicating configuration tables elsewhere.

## Pull requests

Describe the user-visible behavior and the validation you ran. Include focused tests for runtime,
MCP, CLI, or package changes. Documentation-only changes should include the strict MkDocs build and
prek results.

Open a pull request in the [Belgie repository](https://github.com/mplemay/belgie/pulls).
