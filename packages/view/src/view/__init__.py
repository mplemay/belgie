from view._core import Runtime, hello_from_bin

__all__ = ["Runtime", "hello", "hello_from_bin"]


def hello() -> str:
    return hello_from_bin()
