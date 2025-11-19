# Agent Instructions

## Workflow

In general, you **must** follow the following workflow when writing code:

1. Take the users prompt / spec and create a work plan
   - Start by doing deep research to figure out what the user is referencing (ex: library functionality, docs, etc.)
   - Think deeply to understand what you have researched, the users input, and write a detailed plan
   - The plan should include all details necessary for a programmer to implement the design.
   - To accomplish this you should act like a system architect and describe the high-level interfaces and functionality
2. Once you have created the plan **do not** start implementing it right away
   - Prompt me for feedback
   - We will iteratively work together to come up with a design
   - As we iterate on the plan, **only change the things explicitly asked for**
3. Once I explicitly approve the design, begin the implementation
   - Start by writing the code that is the lest dependent on other code first
   - Then write comprehensive tests for that code
   - **Make sure** it it addresses the reasonable edge cases (i.e. **Don't over engineer**)
   - Run the tests to make sure they pass
   - Once the tests pass commit the code
   - Often times, when you commit the code there will be linter / formatter errors
   - Fix those and then attempt to commit again
   - Repeat step three (continuing to take the leaves of the feature dependency tree) until the work plan is done

## Tooling

### Package management

- The package manger for the project is [uv](https://docs.astral.sh/uv/)
- Make `uv add` for core dependencies, `uv add --dev` for developer dependencies, and add optional features to groups
- It is also possible to remove packages using `uv remove`

## Testing

- The project uses `pytest` for testing
- Test files are located in the `src/belgie/__test__/` directory
- Test files should follow the naming convention `test_*.py` or `*_test.py`
- Test functions should be prefixed with `test_`
- Run tests using `uv run pytest`
- The `pytest` settings can be found in the `pyproject.toml`

## Linting

- The project relies on [ruff](https://docs.astral.sh/ruff/) for linting
- The enabled / disabled rules rules can be found in the `pyproject.toml`
- If there is a linter error / warning, try to fix it
- If an error is an edge cases (i.e. requires significant work to fix or is impossible) - add a rule specific ignore

## Type Checking

- The project uses [ty](https://docs.astral.sh/ty/) for type checking
- Similar to the linter, if there is an error that is invalid or extraneous use rule specific suppression
  - For example: `# ty: ignore[unsupported-operator]`

## Pre-Commit Hooks

- The project relies on `pre-commit` to handle the linting, type checking, etc. automatically
- It is configured in the `.pre-commit-config.yaml`

## Conventions

### Git

- Before you commit code, **make sure** you have added comprehensive test cases
- All commit message should be written using the [conventional commits](https://www.conventionalcommits.org/en/v1.0.0/) format
- Commit message **must be** relatively short, written in all lowercase characters, and avoid special characters
- An example message might look like: "feat: added x to y"

### Python

- The targets python versions greater than or equal to 3.12
- Given the project targets a more modern python, use functionality such as:
  - The walrus operator (`:=`)
  - Modern type hints (`dict`)
  - Type parameters `class MyClass[T: MyParent]: ...`
  - The self type (`typing.Self`)
- Prefer importing using `from x import y` instead of `import x`
- Import local modules using the full path (ex: `from my_project.my_module import MyClass`)
- **Don't use** docstrings, instead add inline comments only in places where there is complex or easily breakable logic
