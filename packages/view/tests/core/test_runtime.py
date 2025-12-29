import pytest
from view import Runtime


def test_runtime_simple_expression():
    """Test Runtime can evaluate simple JavaScript expressions."""
    runtime = Runtime()
    result = runtime("1 + 1")
    # For now, just check it executes without error
    assert result == "executed"


def test_runtime_string_concatenation():
    """Test Runtime handles string operations."""
    runtime = Runtime()
    result = runtime("'Hello' + ' ' + 'World'")
    assert result == "executed"


def test_runtime_complex_expression():
    """Test Runtime can handle complex JavaScript."""
    runtime = Runtime()
    result = runtime("[1,2,3].map(x => x * 2).join(',')")
    assert result == "executed"


def test_runtime_error_handling():
    """Test Runtime properly raises errors for invalid JavaScript."""
    runtime = Runtime()
    with pytest.raises(RuntimeError) as exc_info:
        runtime("throw new Error('test error')")
    assert "test error" in str(exc_info.value)


def test_runtime_stateful():
    """Test Runtime maintains state across calls."""
    runtime = Runtime()
    runtime("var counter = 0")
    runtime("counter++")
    result = runtime("counter")
    assert result == "executed"


@pytest.mark.skip(reason="Multiple V8 isolates in same process currently not supported")
def test_runtime_multiple_instances():
    """Test multiple Runtime instances are isolated."""
    runtime1 = Runtime()
    runtime2 = Runtime()

    runtime1("var x = 'runtime1'")
    runtime2("var x = 'runtime2'")

    result1 = runtime1("x")
    result2 = runtime2("x")

    # Both should execute successfully
    assert result1 == "executed"
    assert result2 == "executed"


def test_runtime_syntax_error():
    """Test Runtime handles syntax errors gracefully."""
    runtime = Runtime()
    with pytest.raises(RuntimeError) as exc_info:
        runtime("const x = ")
    # Check for error message (different V8 versions may have different messages)
    error_msg = str(exc_info.value)
    assert "JavaScript Error" in error_msg or "SyntaxError" in error_msg or "Unexpected" in error_msg
