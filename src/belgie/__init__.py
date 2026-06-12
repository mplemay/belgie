from belgie._core import (
    BelgieError,
    BelgieJavaScriptError,
    BelgieModuleError,
    BelgieRuntimeError,
    PackageInstallResult,
    PackageUpdateChange,
    PackageUpdateResult,
    Runtime,
    RuntimeOptions,
    Script,
    ainstall_packages,
    alock_packages,
    aupdate_packages,
    install_packages,
    lock_packages,
    update_packages,
)

type JsonPrimitive = None | bool | int | float | str
type JsonInput = JsonPrimitive | list[JsonInput] | tuple[JsonInput, ...] | dict[str, JsonInput]
type JsonOutput = JsonPrimitive | list[JsonOutput] | dict[str, JsonOutput]
type JsonObject = dict[str, JsonOutput]
type JsonArray = list[JsonOutput]

__all__: tuple[str, ...] = (
    "BelgieError",
    "BelgieJavaScriptError",
    "BelgieModuleError",
    "BelgieRuntimeError",
    "JsonArray",
    "JsonInput",
    "JsonObject",
    "JsonOutput",
    "JsonPrimitive",
    "PackageInstallResult",
    "PackageUpdateChange",
    "PackageUpdateResult",
    "Runtime",
    "RuntimeOptions",
    "Script",
    "ainstall_packages",
    "alock_packages",
    "aupdate_packages",
    "install_packages",
    "lock_packages",
    "update_packages",
)
