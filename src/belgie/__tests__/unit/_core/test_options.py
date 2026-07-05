from __future__ import annotations

from typing import Any, cast

import pytest

from belgie import EnvironmentOptions, Runtime, RuntimeOptions, RuntimePermissions, _core


def test_runtime_options_accepts_default_and_explicit_memory_limits() -> None:
    default_options = RuntimeOptions()
    configured_options = RuntimeOptions(
        max_old_generation_size_mb=64,
        max_young_generation_size_mb=16,
        code_range_size_mb=32,
    )

    assert isinstance(configured_options, RuntimeOptions)
    assert "RuntimeOptions" in repr(default_options)
    assert "max_old_generation_size_mb=Some(64)" in repr(configured_options)
    assert "max_young_generation_size_mb=Some(16)" in repr(configured_options)
    assert "code_range_size_mb=Some(32)" in repr(configured_options)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"max_old_generation_size_mb": 0},
        {"max_young_generation_size_mb": -1},
        {"code_range_size_mb": 0},
    ],
)
def test_runtime_options_reject_non_positive_memory_limits(kwargs: dict[str, int]) -> None:
    with pytest.raises(ValueError, match="positive"):
        RuntimeOptions(**cast("Any", kwargs))


def test_runtime_options_reject_positional_memory_limits() -> None:
    options_type = cast("Any", RuntimeOptions)

    with pytest.raises(TypeError):
        options_type(64)


def test_runtime_options_accept_worker_options() -> None:
    permissions = RuntimePermissions(allow_read=[], deny_net=["example.com"], prompt=False)
    options = RuntimeOptions(
        permissions=permissions,
        seed=123,
        location="https://example.com/app",
        log_level="debug",
        enable_testing_features=True,
        enable_raw_imports=True,
        disable_offscreen_canvas=True,
        trace_ops=["fs"],
    )

    assert isinstance(options, RuntimeOptions)
    assert "seed=Some(123)" in repr(options)
    assert "location=Some" in repr(options)
    assert "debug" in repr(options)
    assert "disable_offscreen_canvas=true" in repr(options).lower()


def test_runtime_options_reject_invalid_worker_options() -> None:
    with pytest.raises(ValueError, match="valid URL"):
        RuntimeOptions(location="not a url")
    with pytest.raises(ValueError, match="log_level"):
        RuntimeOptions(log_level=cast("Any", "verbose"))
    with pytest.raises(ValueError, match="seed"):
        RuntimeOptions(seed=-1)


def test_runtime_options_reject_worker_options_without_environment() -> None:
    with pytest.raises(_core.BelgieRuntimeError, match="Runtime\\(env=Environment"):
        Runtime(options=RuntimeOptions(seed=1))
    with pytest.raises(_core.BelgieRuntimeError, match="Runtime\\(env=Environment"):
        Runtime.from_folder(".", options=RuntimeOptions(permissions=RuntimePermissions.none()))
    with pytest.raises(_core.BelgieRuntimeError, match="Runtime\\(env=Environment"):
        Runtime(options=RuntimeOptions(disable_offscreen_canvas=True))


def test_environment_options_accept_supported_deno_options() -> None:
    options = EnvironmentOptions(
        cache_setting="reload",
        reload=["jsr:@std/path"],
        allow_remote=False,
        allow_json_imports="always",
        node_modules_dir="manual",
        node_modules_linker="hoisted",
        npm_caching="lazy",
        no_npm=True,
        clean_on_install=False,
        production=True,
        skip_types=True,
        unsafely_ignore_certificate_errors=["localhost"],
        import_package_lockfile=True,
        minimum_dependency_age_minutes=0,
    )

    assert isinstance(options, EnvironmentOptions)
    assert "EnvironmentOptions" in repr(options)
    assert "reload" in repr(options)
    assert "always" in repr(options)
    assert "import_package_lockfile=true" in repr(options)
    assert "minimum_dependency_age_minutes=Some(0)" in repr(options)


def test_environment_options_reject_invalid_environment_options() -> None:
    with pytest.raises(ValueError, match="cache_setting"):
        EnvironmentOptions(cache_setting=cast("Any", "fresh"))
    with pytest.raises(ValueError, match="reload"):
        EnvironmentOptions(cache_setting="use", reload=["jsr:@std/path"])
    with pytest.raises(ValueError, match="allow_json_imports"):
        EnvironmentOptions(allow_json_imports=cast("Any", "never"))
    with pytest.raises(ValueError, match="node_modules_dir"):
        EnvironmentOptions(node_modules_dir=cast("Any", "linked"))
    with pytest.raises(ValueError, match="node_modules_linker"):
        EnvironmentOptions(node_modules_linker=cast("Any", "flat"))
    with pytest.raises(ValueError, match="npm_caching"):
        EnvironmentOptions(npm_caching=cast("Any", "none"))
    with pytest.raises(ValueError, match="minimum_dependency_age_minutes"):
        EnvironmentOptions(minimum_dependency_age_minutes=-1)


def test_runtime_permissions_accept_permission_constructors() -> None:
    assert "all" in repr(RuntimePermissions.all())
    assert "none" in repr(RuntimePermissions.none())
    assert "configured" in repr(RuntimePermissions(allow_env=[], ignore_read=[".cache"]))
