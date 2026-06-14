from collections.abc import Awaitable
from os import PathLike

from belgie._core import (
    PackageInstallResult,
    PackageUpdateChange,
    PackageUpdateResult,
    ainstall as ainstall_impl,
    alock as alock_impl,
    aupdate as aupdate_impl,
    install as install_impl,
    lock as lock_impl,
    update as update_impl,
)

__all__: tuple[str, ...] = (
    "PackageInstallResult",
    "PackageUpdateChange",
    "PackageUpdateResult",
    "ainstall",
    "alock",
    "aupdate",
    "install",
    "lock",
    "update",
)


def install(
    cwd: str | PathLike[str] | None = None,
    *,
    groups: list[str] | None = None,
    lockfile_only: bool = False,
) -> PackageInstallResult:
    return install_impl(cwd, groups=groups, lockfile_only=lockfile_only)


def lock(
    cwd: str | PathLike[str] | None = None,
    *,
    groups: list[str] | None = None,
) -> PackageInstallResult:
    return lock_impl(cwd, groups=groups)


def update(
    cwd: str | PathLike[str] | None = None,
    packages: list[str] | None = None,
    *,
    groups: list[str] | None = None,
    latest: bool = False,
    lockfile_only: bool = False,
) -> PackageUpdateResult:
    return update_impl(
        cwd,
        packages,
        groups=groups,
        latest=latest,
        lockfile_only=lockfile_only,
    )


def ainstall(
    cwd: str | PathLike[str] | None = None,
    *,
    groups: list[str] | None = None,
    lockfile_only: bool = False,
) -> Awaitable[PackageInstallResult]:
    return ainstall_impl(cwd, groups=groups, lockfile_only=lockfile_only)


def alock(
    cwd: str | PathLike[str] | None = None,
    *,
    groups: list[str] | None = None,
) -> Awaitable[PackageInstallResult]:
    return alock_impl(cwd, groups=groups)


def aupdate(
    cwd: str | PathLike[str] | None = None,
    packages: list[str] | None = None,
    *,
    groups: list[str] | None = None,
    latest: bool = False,
    lockfile_only: bool = False,
) -> Awaitable[PackageUpdateResult]:
    return aupdate_impl(
        cwd,
        packages,
        groups=groups,
        latest=latest,
        lockfile_only=lockfile_only,
    )
