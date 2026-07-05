from __future__ import annotations

import pytest

from belgie import Command, Environment, Runtime, Script
from belgie.__tests__.helpers.local_package import write_local_package_with_bin

pytestmark = pytest.mark.integration


def test_environment_runtime_keeps_all_script_and_command_workers_snapshot_backed(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.chdir(tmp_path)
    with Environment({"semver": "7.7.2"}) as env:
        env.install()
        with Runtime(env=env) as runtime:
            assert runtime(Script("export default () => 41"))() == 41
            assert runtime(Script("export default () => 42"))() == 42
            assert runtime(Command("semver"))("--help") is None
            assert runtime(Script("export default async () => 43"))() == 43

    assert list(tmp_path.iterdir()) == []


def test_environment_runtime_runs_local_file_package_script_and_command(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.chdir(tmp_path)
    write_local_package_with_bin(tmp_path, bin_name="local-pkg")

    source = 'import { answer } from "local-pkg"; export default () => answer;'
    with Environment({"local-pkg": "file:./local-pkg"}) as env:
        env.install()
        with Runtime(env=env) as runtime:
            assert runtime(Script(source))() == 42
            assert runtime(Command("local-pkg"))() is None

    assert (tmp_path / "local-command.txt").read_text(encoding="utf-8") == "ok\n"
