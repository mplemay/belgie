from __future__ import annotations

from typing import Any, cast

import pytest

from belgie import Command
from belgie.__tests__.unit._core.conftest import StringPath


def test_command_accepts_name_cwd_and_environment(tmp_path) -> None:
    command = Command(
        " vite ",
        cwd=StringPath(str(tmp_path)),
        env={"NODE_ENV": "production"},
        module=True,
    )

    assert isinstance(command, Command)
    text = repr(command).replace("\\\\", "\\")
    assert 'name="vite"' in text
    assert f'cwd=Some("{tmp_path.resolve()}")' in text
    assert 'env={"NODE_ENV": "production"}' in text
    assert "module=true" in text


def test_command_defaults_module_mode_to_false() -> None:
    assert "module=false" in repr(Command("vite"))


@pytest.mark.parametrize("name", ["", "   "])
def test_command_rejects_empty_names(name: str) -> None:
    with pytest.raises(ValueError, match="must not be empty"):
        Command(name)


def test_command_rejects_invalid_cwd_and_environment() -> None:
    with pytest.raises(TypeError):
        Command("vite", cwd=cast("Any", object()))
    with pytest.raises(TypeError):
        Command("vite", env=cast("Any", {"NODE_ENV": 1}))
