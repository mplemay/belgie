from view import hello


def test_hello_function():
    """Test the hello function returns a string."""
    result = hello()
    assert isinstance(result, str)
    assert len(result) > 0
