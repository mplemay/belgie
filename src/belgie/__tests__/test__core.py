from belgie._core import hello_from_bin

def test_hello_from_bin() -> None:
    assert hello_from_bin() == "Hello from belgie!"
