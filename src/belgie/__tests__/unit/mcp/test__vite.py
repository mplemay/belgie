from __future__ import annotations

import threading
from collections.abc import Iterator
from pathlib import Path
from typing import TYPE_CHECKING, cast

import pytest

from belgie.mcp import _vite as vite_module
from belgie.mcp._vite import (
    _load_vite_project,
    _reset_vite_state_for_tests,
    _shutdown_vite_dev_servers,
    _ViteDevServer,
    _ViteProject,
    build_vite_once,
    ensure_vite_dev_server,
)
from belgie.mcp._widgets import read_widget_html

if TYPE_CHECKING:
    from belgie import Environment, Runtime


@pytest.fixture(autouse=True)
def reset_vite_state() -> Iterator[None]:
    _reset_vite_state_for_tests()
    read_widget_html.cache_clear()
    yield
    _reset_vite_state_for_tests()
    read_widget_html.cache_clear()


def test_load_vite_project_reads_dependencies_module_and_lockfile(tmp_path: Path) -> None:
    local_package = tmp_path / "packages" / "plugin"
    local_package.mkdir(parents=True)
    (tmp_path / "deno.lock").write_text("{}\n", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text(
        """
[tool.belgie]
module = true

[tool.belgie.dependencies]
plugin = "file:packages/plugin"
vite = "npm:vite@8"
""".lstrip(),
        encoding="utf-8",
    )

    project = _load_vite_project(tmp_path)

    assert project.root == tmp_path
    assert project.dependencies == {
        "plugin": f"file:{local_package.resolve().as_posix()}",
        "vite": "npm:vite@8",
    }
    assert project.module
    assert project.lockfile == tmp_path / "deno.lock"


@pytest.mark.parametrize(
    ("contents", "message"),
    [
        ("[tool.belgie]\nmodule = false\n", "dependencies.*empty or missing"),
        ('[tool.belgie.dependencies]\nreact = "npm:react@19"\n', "must contain a 'vite' entry"),
    ],
)
def test_load_vite_project_requires_vite_dependency(
    tmp_path: Path,
    contents: str,
    message: str,
) -> None:
    (tmp_path / "pyproject.toml").write_text(contents, encoding="utf-8")

    with pytest.raises(RuntimeError, match=message):
        _load_vite_project(tmp_path)


def test_build_vite_once_builds_once_and_invalidates_html_cache(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    html_path = tmp_path / "dist" / "widgets" / "clock" / "index.html"
    html_path.parent.mkdir(parents=True)
    html_path.write_text("old", encoding="utf-8")
    assert read_widget_html(html_path) == "old"
    project = _ViteProject(
        root=tmp_path,
        dependencies={"vite": "npm:vite@8"},
        module=False,
        lockfile=None,
    )
    calls: list[tuple[_ViteProject, tuple[str, ...]]] = []

    monkeypatch.setattr(vite_module, "_load_vite_project", lambda _project: project)

    def run_vite(vite_project: _ViteProject, *args: str) -> None:
        calls.append((vite_project, args))
        html_path.write_text("new", encoding="utf-8")

    monkeypatch.setattr(vite_module, "_run_vite_command", run_vite)

    build_vite_once(tmp_path)
    build_vite_once(tmp_path)

    assert calls == [(project, ("build",))]
    assert read_widget_html(html_path) == "new"


def test_ensure_vite_dev_server_reuses_external_server(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(vite_module, "_is_address_reachable", lambda _host, _port: True)

    ensure_vite_dev_server(tmp_path)

    assert vite_module.DEV_SERVERS == {}


def test_ensure_vite_dev_server_starts_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reachable = threading.Event()
    release = threading.Event()
    starts: list[_ViteDevServer] = []

    monkeypatch.setattr(
        vite_module,
        "_is_address_reachable",
        lambda _host, _port: reachable.is_set(),
    )

    def run_vite(server: _ViteDevServer) -> None:
        starts.append(server)
        reachable.set()
        release.wait(timeout=1)

    monkeypatch.setattr(vite_module, "_run_vite_dev_server", run_vite)

    try:
        ensure_vite_dev_server(tmp_path)
        ensure_vite_dev_server(tmp_path)
        assert len(starts) == 1
        assert len(vite_module.DEV_SERVERS) == 1
    finally:
        release.set()
        thread = starts[0].thread if starts else None
        if thread is not None:
            thread.join(timeout=1)


def test_ensure_vite_dev_server_rejects_owned_port_for_another_project(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reachable = threading.Event()
    release = threading.Event()
    starts: list[_ViteDevServer] = []

    monkeypatch.setattr(
        vite_module,
        "_is_address_reachable",
        lambda _host, _port: reachable.is_set(),
    )

    def run_vite(server: _ViteDevServer) -> None:
        starts.append(server)
        reachable.set()
        release.wait(timeout=1)

    monkeypatch.setattr(vite_module, "_run_vite_dev_server", run_vite)

    try:
        ensure_vite_dev_server(tmp_path / "first")
        with pytest.raises(RuntimeError, match="already manages"):
            ensure_vite_dev_server(tmp_path / "second")
    finally:
        release.set()
        thread = starts[0].thread if starts else None
        if thread is not None:
            thread.join(timeout=1)


def test_ensure_vite_dev_server_reports_start_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(vite_module, "_is_address_reachable", lambda _host, _port: False)

    def fail_start(server: _ViteDevServer) -> None:
        with server.state_lock:
            server.error = RuntimeError("boom")

    monkeypatch.setattr(vite_module, "_run_vite_dev_server", fail_start)

    with pytest.raises(RuntimeError, match="Unable to start.*boom"):
        ensure_vite_dev_server(tmp_path)


def test_ensure_vite_dev_server_reports_timeout(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    release = threading.Event()
    starts: list[_ViteDevServer] = []
    monkeypatch.setattr(vite_module, "_is_address_reachable", lambda _host, _port: False)
    monkeypatch.setattr(vite_module, "DEV_START_TIMEOUT_SECONDS", 0.03)
    monkeypatch.setattr(vite_module, "DEV_POLL_INTERVAL_SECONDS", 0.005)

    def never_ready(server: _ViteDevServer) -> None:
        starts.append(server)
        release.wait(timeout=1)

    monkeypatch.setattr(vite_module, "_run_vite_dev_server", never_ready)

    try:
        with pytest.raises(RuntimeError, match="Timed out waiting"):
            ensure_vite_dev_server(tmp_path)
    finally:
        release.set()
        thread = starts[0].thread if starts else None
        if thread is not None:
            thread.join(timeout=1)


def test_shutdown_closes_only_owned_runtime_and_environment(tmp_path: Path) -> None:
    exits: list[str] = []

    class Context:
        def __init__(self, name: str) -> None:
            self.name = name

        def __exit__(self, *_args: object) -> None:
            exits.append(self.name)

    server = _ViteDevServer(project=tmp_path, host="127.0.0.1", port=5173)
    server.runtime = cast("Runtime", Context("runtime"))
    server.environment = cast("Environment", Context("environment"))
    vite_module.DEV_SERVERS[("127.0.0.1", 5173)] = server

    _shutdown_vite_dev_servers()

    assert exits == ["runtime", "environment"]
    assert vite_module.DEV_SERVERS == {}
