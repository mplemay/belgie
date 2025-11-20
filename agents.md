# Agent Instructions

## Workflow

In general, you **must** follow the following workflow when writing code:

1. **Research and understand the task**
   - Explore the existing codebase to understand current architecture and patterns
     - Use glob/grep to find relevant files and understand existing implementations
     - Read related code to understand how similar features are structured
     - Identify existing utilities, base classes, and patterns to leverage
   - Research external solutions and best practices
     - Search the web for similar implementations in other projects
     - Research relevant libraries and their APIs
     - Understand common patterns and anti-patterns for the feature type
     - Investigate potential dependencies and their trade-offs
   - Gather requirements and constraints
     - Clarify ambiguous requirements with the user if needed
     - Identify edge cases and potential issues
     - Understand performance, security, and compatibility requirements

2. **Create a design document**
   - **Use the design document template** ([design/000-design-template.md](design/000-design-template.md)) to structure your plan
   - See the complete example ([design/000-design-example.md](design/000-design-example.md)) for a filled-out design document
   - Act as a system architect and describe the high-level interfaces and functionality
   - The design document should include:
     - High-level description and goals
     - Workflows with mermaid diagrams (call graphs, sequence diagrams)
     - Dependency graphs showing existing and new dependencies
     - Implementation order (based on dependency graph leaf nodes)
     - Libraries to be added and their dependency groups
     - API design with code stubs and inline comments
     - Testing strategy organized by module
   - The plan should include all details necessary for a programmer to implement the design

3. **Iterate on the design**
   - Once you have created the plan **do not** start implementing it right away
   - Prompt me for feedback
   - We will iteratively work together to come up with a design
   - As we iterate on the plan, **only change the things explicitly asked for**

4. **Implement the approved design**
   - Once I explicitly approve the design, begin the implementation
   - Start by writing the code that is the least dependent on other code first
   - Then write comprehensive tests for that code
   - **Make sure** it addresses the reasonable edge cases (i.e. **Don't over engineer**)
   - Run the tests to make sure they pass
   - Once the tests pass commit the code
   - Often times, when you commit the code there will be linter / formatter errors
   - Fix those and then attempt to commit again
   - Repeat step four (continuing to take the leaves of the feature dependency tree) until the work plan is done

## Tooling

### Package management

- The package manger for the project is [uv](https://docs.astral.sh/uv/)
- Make `uv add` for core dependencies, `uv add --dev` for developer dependencies, and add optional features to groups
- It is also possible to remove packages using `uv remove`

## Testing

- The project uses `pytest` for testing
- Test files are located in the `src/belgie/__test__/` directory
- Test files should mirror the folder structure and use corresponding file names
  - Test file with matching name contains unit tests
  - Integration tests use `_integration` suffix
  - Example: `module_x/test_corresponding_file.py` (unit tests)
  - Example: `module_x/test_corresponding_file_integration.py` (integration tests)
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
- **When to use `# ty: ignore`**:
  - Type checker reports false positives due to dynamic code
  - Third-party library has incorrect or missing type stubs
  - Valid code that the type checker cannot understand (e.g., certain metaclass patterns)
  - Edge cases where adding correct types would make code significantly more complex
- **Best practices for type ignore comments**:
  - Always use specific error codes: `# ty: ignore[error-code]` (not bare `# ty: ignore`)
  - Add inline explanation when the reason isn't obvious: `# ty: ignore[attr-defined]  # Dynamic attribute from metaclass`
  - Consider if the code can be refactored to avoid the ignore
  - Common error codes:
    - `[attr-defined]` - Attribute doesn't exist on type
    - `[arg-type]` - Argument has wrong type
    - `[return-value]` - Return type doesn't match annotation
    - `[assignment]` - Assignment target incompatible with value
    - `[union-attr]` - Attribute only on some union members
    - `[index]` - Invalid index operation

## Pre-Commit Hooks

- The project relies on `pre-commit` to handle the linting, type checking, etc. automatically
- It is configured in the `.pre-commit-config.yaml`

## Conventions

### Git

- Before you commit code, **make sure** you have added comprehensive test cases
- All commit message should be written using the [conventional commits](https://www.conventionalcommits.org/en/v1.0.0/) format
- Commit message **must be** relatively short, written in all lowercase characters, and avoid special characters
- An example message might look like: "feat: added x to y"
- **Branch naming conventions**:
  - Use descriptive, kebab-case branch names
  - Prefix branches by type: `feature/`, `bugfix/`, `refactor/`, `docs/`, `test/`
  - Include brief description of the work
  - Examples:
    - `feature/config-validator`
    - `bugfix/fix-validation-error-messages`
    - `refactor/simplify-schema-builder`
    - `docs/update-readme-examples`

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
- **Don't use** docstrings, instead add inline comments only in places where there is complex or easily breakable logic
