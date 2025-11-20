# Contributing to Belgie

Thank you for your interest in contributing to Belgie! This document provides guidelines and instructions for contributing.

## Code of Conduct

Be respectful, inclusive, and professional in all interactions. We're building a welcoming community for everyone.

## How Can I Contribute?

### Reporting Bugs

Before creating bug reports, please check existing issues to avoid duplicates. When creating a bug report, include:

- **Clear title** - Descriptive summary of the issue
- **Steps to reproduce** - Detailed steps to reproduce the behavior
- **Expected behavior** - What you expected to happen
- **Actual behavior** - What actually happened
- **Environment** - Python version, OS, Belgie version
- **Code samples** - Minimal reproducible example if possible

### Suggesting Enhancements

Enhancement suggestions are tracked as GitHub issues. When creating an enhancement suggestion, include:

- **Clear title** - Descriptive summary of the enhancement
- **Use case** - Why this enhancement would be useful
- **Proposed solution** - How you envision it working
- **Alternatives** - Other solutions you've considered

### Pull Requests

1. **Fork the repository** and create your branch from `main`
2. **Install dependencies**:
   ```bash
   git clone https://github.com/yourusername/brugge.git
   cd brugge
   uv venv
   source .venv/bin/activate  # or `.venv\Scripts\activate` on Windows
   uv pip install -e ".[dev]"
   ```

3. **Make your changes**:
   - Write clear, readable code
   - Follow existing code style
   - Add tests for new functionality
   - Update documentation as needed

4. **Run tests and checks**:
   ```bash
   # Run tests
   pytest

   # Run with coverage
   pytest --cov=src/brugge --cov-report=term-missing

   # Run linting
   ruff check .

   # Run formatting
   ruff format .

   # Run type checking
   ty check .

   # Run all pre-commit hooks
   pre-commit run --all-files
   ```

5. **Commit your changes**:
   - Use clear, descriptive commit messages
   - Follow conventional commits format:
     ```
     feat: add GitHub OAuth provider
     fix: correct session expiration logic
     docs: update configuration guide
     test: add tests for scope validation
     refactor: simplify auth dependency
     ```

6. **Push to your fork** and submit a pull request

7. **Wait for review** - Maintainers will review your PR and may request changes

## Development Guidelines

### Code Style

- Follow PEP 8 guidelines
- Use type hints for all functions and methods
- Write docstrings for public APIs (Google style)
- Keep functions focused and small
- Use meaningful variable names

### Testing

- Write tests for all new functionality
- Maintain or improve code coverage
- Include unit tests and integration tests
- Test edge cases and error conditions
- Use fixtures for common setup

### Documentation

- Update README.md for new features
- Add docstrings to new classes and methods
- Update relevant documentation in `docs/`
- Include examples for new functionality
- Keep documentation clear and concise

### Type Hints

- Use type hints for all function signatures
- Use protocol types for flexibility
- Leverage Python 3.12+ type features
- Run type checker before committing

## Project Structure

```
brugge/
├── src/brugge/          # Main package
│   ├── __init__.py      # Package exports
│   ├── core/            # Core authentication logic
│   ├── adapters/        # Database adapters
│   ├── providers/       # OAuth providers
│   ├── session/         # Session management
│   ├── protocols/       # Type protocols
│   ├── utils/           # Utility functions
│   └── __test__/        # Tests
├── examples/            # Example applications
├── docs/                # Documentation
├── pyproject.toml       # Project configuration
└── README.md            # Main documentation
```

## Adding a New OAuth Provider

To add a new OAuth provider (e.g., GitHub):

1. **Create provider class** in `src/brugge/providers/`:
   ```python
   class GitHubOAuthProvider:
       def __init__(self, client_id, client_secret, redirect_uri, scopes):
           ...

       def generate_authorization_url(self, state):
           ...

       async def exchange_code_for_tokens(self, code):
           ...

       async def get_user_info(self, access_token):
           ...
   ```

2. **Add settings** in `src/brugge/core/settings.py`:
   ```python
   class GitHubOAuthSettings(BaseSettings):
       client_id: str
       client_secret: str
       redirect_uri: str
       scopes: list[str] = ["user:email"]
   ```

3. **Update Auth class** to support the new provider

4. **Write comprehensive tests** for the provider

5. **Document the provider** in relevant guides

6. **Add example** showing provider usage

## Testing

### Running Tests

```bash
# All tests
pytest

# Specific test file
pytest src/brugge/__test__/test_auth_core.py

# Specific test
pytest src/brugge/__test__/test_auth_core.py::test_auth_initialization

# With coverage
pytest --cov=src/brugge --cov-report=html

# Verbose output
pytest -v

# Stop on first failure
pytest -x
```

### Writing Tests

```python
import pytest
from brugge import Auth, AuthSettings

async def test_my_feature():
    # Arrange
    settings = AuthSettings(...)
    auth = Auth(settings=settings, adapter=adapter)

    # Act
    result = await auth.some_method()

    # Assert
    assert result == expected_value
```

## Documentation

### Building Docs Locally

Documentation is in Markdown format in the `docs/` directory. No build step required.

### Writing Documentation

- Use clear, simple language
- Include code examples
- Provide context and explanations
- Link to related documentation
- Test all code examples

## Release Process

Maintainers handle releases:

1. Update version in `pyproject.toml`
2. Update `CHANGELOG.md`
3. Create git tag
4. Build and publish to PyPI
5. Create GitHub release

## Questions?

- Open an issue for questions
- Check existing documentation
- Look at examples in `examples/`
- Review existing code for patterns

## License

By contributing, you agree that your contributions will be licensed under the MIT License.

## Recognition

Contributors are recognized in the README and release notes. Thank you for making Belgie better!
