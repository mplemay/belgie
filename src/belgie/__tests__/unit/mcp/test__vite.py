from __future__ import annotations

import subprocess
import sys
import threading
from collections.abc import Iterator
from contextlib import nullcontext
from email.message import Message
from pathlib import Path
from unittest.mock import MagicMock
from urllib.error import HTTPError, URLError

import pytest

from belgie.mcp import _vite as vite_module
from belgie.mcp._vite import (
    _filter_rolldown_teardown_stderr,
    _load_vite_project,
    _reset_vite_state_for_tests,
    _shutdown_vite_dev_servers,
    _ViteDevServer,
    _ViteProject,
    ensure_vite_dev_server,
    load_production_widget,
)
from belgie.mcp._widgets import read_widget_html


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


def test_load_production_widget_builds_once_and_invalidates_html_cache(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    widget = tmp_path / "src" / "widgets" / "clock" / "widget.tsx"
    widget.parent.mkdir(parents=True)
    widget.write_text("export default function Clock() {}\n", encoding="utf-8")
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

    assert load_production_widget(tmp_path, widget) == "new"
    assert load_production_widget(tmp_path, widget) == "new"

    assert calls == [(project, ("build",))]
    assert tmp_path.resolve() in vite_module.BUILT_PROJECTS
    assert read_widget_html(html_path) == "new"


def test_load_production_widget_retries_build_after_missing_html(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    widget = tmp_path / "src" / "widgets" / "clock" / "widget.tsx"
    widget.parent.mkdir(parents=True)
    widget.write_text("export default function Clock() {}\n", encoding="utf-8")
    html_path = tmp_path / "dist" / "widgets" / "clock" / "index.html"
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

    monkeypatch.setattr(vite_module, "_run_vite_command", run_vite)

    with pytest.raises(FileNotFoundError, match="Built widget HTML does not exist"):
        load_production_widget(tmp_path, widget)

    assert tmp_path.resolve() not in vite_module.BUILT_PROJECTS
    assert calls == [(project, ("build",))]

    html_path.parent.mkdir(parents=True)
    html_path.write_text("built", encoding="utf-8")

    assert load_production_widget(tmp_path, widget) == "built"
    assert calls == [(project, ("build",)), (project, ("build",))]
    assert tmp_path.resolve() in vite_module.BUILT_PROJECTS


def test_ensure_vite_dev_server_reuses_external_server(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(vite_module, "_is_vite_dev_server_ready", lambda _host, _port: True)

    ensure_vite_dev_server(tmp_path)

    assert vite_module.DEV_SERVERS == {}


def test_vite_dev_server_readiness_requires_http_response(monkeypatch: pytest.MonkeyPatch) -> None:
    requests: list[tuple[str, float]] = []

    def unavailable(url: str, *, timeout: float) -> None:
        requests.append((url, timeout))
        raise URLError(ConnectionRefusedError())

    monkeypatch.setattr(vite_module, "urlopen", unavailable)
    assert not vite_module._is_vite_dev_server_ready("127.0.0.1", 4173)

    def ready(url: str, *, timeout: float) -> nullcontext[None]:
        requests.append((url, timeout))
        return nullcontext()

    monkeypatch.setattr(vite_module, "urlopen", ready)
    assert vite_module._is_vite_dev_server_ready("127.0.0.1", 4173)
    assert requests == [
        ("http://127.0.0.1:4173", vite_module.DEV_PROBE_TIMEOUT_SECONDS),
        ("http://127.0.0.1:4173", vite_module.DEV_PROBE_TIMEOUT_SECONDS),
    ]


def test_vite_dev_server_readiness_accepts_http_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def not_found(url: str, *, timeout: float) -> None:
        assert timeout == vite_module.DEV_PROBE_TIMEOUT_SECONDS
        raise HTTPError(url, 404, "Not Found", Message(), None)

    monkeypatch.setattr(vite_module, "urlopen", not_found)

    assert vite_module._is_vite_dev_server_ready("127.0.0.1", 4173)


def test_ensure_vite_dev_server_starts_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reachable = threading.Event()
    release = threading.Event()
    starts: list[_ViteDevServer] = []

    monkeypatch.setattr(
        vite_module,
        "_is_vite_dev_server_ready",
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
        "_is_vite_dev_server_ready",
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
    monkeypatch.setattr(vite_module, "_is_vite_dev_server_ready", lambda _host, _port: False)

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
    monkeypatch.setattr(vite_module, "_is_vite_dev_server_ready", lambda _host, _port: False)
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


def test_shutdown_stops_owned_subprocess(tmp_path: Path) -> None:
    process = MagicMock(spec=subprocess.Popen)
    process.poll.return_value = None
    process.wait.return_value = 0
    process.stderr = None
    server = _ViteDevServer(project=tmp_path, host="127.0.0.1", port=5173)
    server.process = process
    server.stderr_chunks.append(b"vite ready\n")
    vite_module.DEV_SERVERS[("127.0.0.1", 5173)] = server

    _shutdown_vite_dev_servers()

    if sys.platform == "win32":
        process.terminate.assert_called_once()
    else:
        process.send_signal.assert_called()
    assert server.process is None
    assert vite_module.DEV_SERVERS == {}


def test_filter_rolldown_teardown_stderr_drops_panic_banner() -> None:
    panic = (
        "Rolldown panicked. This is a bug in Rolldown, not your code.\n"
        "\n"
        "thread 'rolldown-worker' (68675) panicked at crates/rolldown/src/module_loader/module_task.rs:239:30:\n"
        "ModuleLoader channel closed while sending module completion - main thread terminated unexpectedly: "
        "SendError { .. }\n"
        "\n"
        "Please report this issue at: https://github.com/rolldown/rolldown/issues/new?template=panic_report.yml\n"
    )
    kept = "vite v8.2.0 building for production...\n"
    assert _filter_rolldown_teardown_stderr(kept + panic) == kept
    assert _filter_rolldown_teardown_stderr(panic) == ""
