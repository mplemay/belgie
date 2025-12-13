import importlib
import sys
from importlib.abc import MetaPathFinder


class _BlockModulesFinder(MetaPathFinder):
    def __init__(self, blocked: set[str]) -> None:
        self._blocked = blocked

    def find_spec(self, fullname: str, path, target=None):
        if fullname in self._blocked:
            raise ImportError(f"blocked import: {fullname}")


def _reload_belgie_with_blocked(blocked: set[str]):
    sys.modules.pop("belgie", None)
    for name in list(sys.modules):
        if name.startswith("belgie."):
            sys.modules.pop(name, None)

    finder = _BlockModulesFinder(blocked)
    sys.meta_path.insert(0, finder)
    try:
        return importlib.import_module("belgie")
    finally:
        sys.meta_path.remove(finder)


def test_root_reexports_when_modules_available():
    belgie = importlib.reload(importlib.import_module("belgie"))
    assert hasattr(belgie, "Auth")
    assert hasattr(belgie, "Trace")


def test_root_import_works_without_auth_or_trace():
    belgie = _reload_belgie_with_blocked({"belgie.auth", "belgie.trace"})
    try:
        assert belgie.__all__ == ["__version__"]
        assert not hasattr(belgie, "Auth")
        assert not hasattr(belgie, "Trace")
    finally:
        sys.modules.pop("belgie", None)
        for name in list(sys.modules):
            if name.startswith("belgie."):
                sys.modules.pop(name, None)
