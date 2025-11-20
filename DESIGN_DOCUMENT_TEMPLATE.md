# Design Document: [Feature/Module Name]

## Overview

### High-Level Description
<!-- Provide a clear, concise description of what this feature/module does and why it's needed -->
[Describe the feature, its purpose, and the problem it solves]

### Goals
<!-- What are the primary objectives of this feature? -->
- [Goal 1]
- [Goal 2]
- [Goal 3]

### Non-Goals
<!-- What is explicitly out of scope? -->
- [Non-goal 1]
- [Non-goal 2]

## Workflows

### Call Graph
<!-- Use mermaid to show the flow of function calls and control flow -->
```mermaid
graph TD
    A[Entry Point] --> B[Function 1]
    A --> C[Function 2]
    B --> D[Helper Function]
    C --> D
    D --> E[Return Result]
```

### Sequence Diagram (Optional)
<!-- If the feature involves complex interactions, add a sequence diagram -->
```mermaid
sequenceDiagram
    participant User
    participant Module
    participant Dependency

    User->>Module: call_function()
    Module->>Dependency: process_data()
    Dependency-->>Module: result
    Module-->>User: response
```

## Dependencies

### Dependency Graph
<!-- Show both existing and new dependencies. Mark nodes as [EXISTING] or [NEW] -->
<!-- The graph should be structured so "leaf" nodes (no dependencies) are clear -->
```mermaid
graph TD
    NewFeature[NEW: NewFeature]
    NewHelper[NEW: NewHelper]
    ExistingModule[EXISTING: ExistingModule]
    ExistingUtil[EXISTING: ExistingUtil]
    ExistingBase[EXISTING: BaseClass]

    NewFeature --> NewHelper
    NewFeature --> ExistingModule
    NewHelper --> ExistingUtil
    ExistingModule --> ExistingBase

    style NewFeature fill:#90EE90
    style NewHelper fill:#90EE90
    style ExistingModule fill:#87CEEB
    style ExistingUtil fill:#87CEEB
    style ExistingBase fill:#87CEEB
```

### Implementation Order
<!-- Based on the dependency graph, list the order to implement (leaf nodes first) -->
1. **[EXISTING] BaseClass** - Already exists, no implementation needed
2. **[EXISTING] ExistingUtil** - Already exists, no implementation needed
3. **[NEW] NewHelper** - Implement first (leaf node, only depends on existing code)
4. **[EXISTING] ExistingModule** - Already exists, no implementation needed
5. **[NEW] NewFeature** - Implement last (depends on NewHelper and ExistingModule)

## Libraries

### New Libraries
<!-- List new libraries to be added and their dependency groups -->

| Library | Version | Purpose | Dependency Group | Command |
|---------|---------|---------|------------------|---------|
| `library-name` | `>=1.0.0` | [Purpose] | `dev` / `optional-group` / core | `uv add library-name` or `uv add --dev library-name` |

### Existing Libraries
<!-- List existing libraries that will be leveraged -->

| Library | Current Version | Purpose | Dependency Group |
|---------|-----------------|---------|------------------|
| `existing-lib` | `>=1.0.0` | [Purpose] | `dev` / core |

## Detailed Design

### Module Structure
<!-- Show the file/module structure -->
```
src/belgie/
├── feature_name/
│   ├── __init__.py
│   ├── main.py          # Entry point and main logic
│   ├── helper.py        # Helper functions
│   └── types.py         # Type definitions
└── __test__/
    └── test_feature_name.py
```

### Code Stubs

#### File: `src/belgie/feature_name/types.py`
```python
# Type definitions for the feature

from typing import TypedDict

class ConfigType(TypedDict):
    """Configuration for the feature."""
    option1: str
    option2: int

class ResultType(TypedDict):
    """Result returned by the feature."""
    status: str
    data: dict[str, str]
```

#### File: `src/belgie/feature_name/helper.py`
```python
# Helper functions for the feature

from belgie.existing_module import existing_function

def process_input(data: str) -> dict[str, str]:
    """Process input data and return structured result.

    This function will:
    1. Validate the input data
    2. Transform it into the required format
    3. Return a dictionary with processed data
    """
    # Validate input
    # Transform data
    # Return result
    pass

def validate_config(config: dict[str, str]) -> bool:
    """Validate configuration parameters.

    This function will:
    1. Check all required keys are present
    2. Validate value types and ranges
    3. Return True if valid, False otherwise
    """
    # Check required keys
    # Validate types
    # Validate ranges
    pass
```

#### File: `src/belgie/feature_name/main.py`
```python
# Main implementation of the feature

from typing import Self

from belgie.existing_module import BaseClass
from belgie.feature_name.helper import process_input, validate_config
from belgie.feature_name.types import ConfigType, ResultType

class NewFeature(BaseClass):
    """Main class implementing the new feature."""

    def __init__(self: Self, config: ConfigType) -> None:
        """Initialize the feature with configuration.

        This will:
        1. Validate the config
        2. Initialize parent class
        3. Set up internal state
        """
        # Validate config using validate_config()
        # Call parent __init__
        # Initialize internal state
        pass

    def execute(self: Self, input_data: str) -> ResultType:
        """Execute the main feature logic.

        This will:
        1. Process input using helper functions
        2. Perform core business logic
        3. Return structured result
        """
        # Process input using process_input()
        # Execute core logic
        # Build and return result
        pass

    def _internal_helper(self: Self, data: dict[str, str]) -> str:
        """Internal helper method for processing.

        This will:
        1. Transform dictionary data
        2. Apply business rules
        3. Return formatted string
        """
        # Transform data
        # Apply rules
        # Return formatted result
        pass
```

#### File: `src/belgie/feature_name/__init__.py`
```python
# Public API exports

from belgie.feature_name.main import NewFeature
from belgie.feature_name.types import ConfigType, ResultType

__all__ = ["NewFeature", "ConfigType", "ResultType"]
```

### Testing Strategy
<!-- Describe how the feature will be tested -->

#### Test Structure
- **Unit Tests**: Test individual functions in isolation
- **Integration Tests**: Test the feature as a whole
- **Edge Cases**: [List specific edge cases to test]

#### Test File: `src/belgie/__test__/test_feature_name.py`
```python
# Tests for the new feature

import pytest

from belgie.feature_name import NewFeature, ConfigType

def test_feature_initialization():
    """Test that feature initializes correctly with valid config."""
    # Create valid config
    # Initialize feature
    # Assert state is correct
    pass

def test_feature_execution():
    """Test main execution path."""
    # Initialize feature
    # Call execute with test data
    # Assert result matches expected output
    pass

def test_invalid_config():
    """Test that invalid config raises appropriate error."""
    # Create invalid config
    # Attempt to initialize feature
    # Assert appropriate exception is raised
    pass

@pytest.mark.parametrize("input_data,expected", [
    ("test1", {"status": "success"}),
    ("test2", {"status": "success"}),
])
def test_parametrized_execution(input_data: str, expected: dict[str, str]):
    """Test execution with various inputs."""
    # Initialize feature
    # Execute with input_data
    # Assert result matches expected
    pass
```

## Implementation Checklist

<!-- Track implementation progress -->
- [ ] Implement helper functions (leaf nodes)
- [ ] Write tests for helper functions
- [ ] Implement main feature class
- [ ] Write tests for main feature
- [ ] Add integration tests
- [ ] Update documentation
- [ ] Add type hints and run type checker
- [ ] Run linter and fix issues
- [ ] Verify all tests pass
- [ ] Create PR

## Open Questions

<!-- List any unresolved questions or decisions needed -->
1. [Question 1]?
2. [Question 2]?

## Future Enhancements

<!-- Features or improvements to consider after initial implementation -->
- [Enhancement 1]
- [Enhancement 2]
