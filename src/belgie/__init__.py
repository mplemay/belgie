from belgie._core import (
    Command,
    Environment,
    EnvironmentInstallResult,
    EnvironmentOptions,
    EnvironmentUpdateChange,
    EnvironmentUpdateResult,
    Runtime,
    RuntimeOptions,
    RuntimePermissions,
    Script,
)

type JsonPrimitive = None | bool | int | float | str
type JsonInput = JsonPrimitive | list[JsonInput] | tuple[JsonInput, ...] | dict[str, JsonInput]
type JsonOutput = JsonPrimitive | list[JsonOutput] | dict[str, JsonOutput]
type JsonObject = dict[str, JsonOutput]
type JsonArray = list[JsonOutput]

__all__: tuple[str, ...] = (
    "Command",
    "Environment",
    "EnvironmentInstallResult",
    "EnvironmentOptions",
    "EnvironmentUpdateChange",
    "EnvironmentUpdateResult",
    "JsonArray",
    "JsonInput",
    "JsonObject",
    "JsonOutput",
    "JsonPrimitive",
    "Runtime",
    "RuntimeOptions",
    "RuntimePermissions",
    "Script",
)
