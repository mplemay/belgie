import os
import sys
from importlib import import_module
from types import ModuleType
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from belgie._core import Environment, Runtime, RuntimeOptions, Script


def _load_core_module() -> ModuleType:
    get_flags = getattr(sys, "getdlopenflags", None)
    set_flags = getattr(sys, "setdlopenflags", None)
    rtld_global = getattr(os, "RTLD_GLOBAL", None)
    if not callable(get_flags) or not callable(set_flags) or not isinstance(rtld_global, int):
        return import_module("belgie._core")

    previous_flags = get_flags()
    set_flags(previous_flags | rtld_global)
    try:
        return import_module("belgie._core")
    finally:
        set_flags(previous_flags)


if not TYPE_CHECKING:
    CORE_MODULE: Final[ModuleType] = _load_core_module()
    Environment = CORE_MODULE.Environment
    Runtime = CORE_MODULE.Runtime
    RuntimeOptions = CORE_MODULE.RuntimeOptions
    Script = CORE_MODULE.Script

type JsonPrimitive = None | bool | int | float | str
type JsonInput = JsonPrimitive | list[JsonInput] | tuple[JsonInput, ...] | dict[str, JsonInput]
type JsonOutput = JsonPrimitive | list[JsonOutput] | dict[str, JsonOutput]
type JsonObject = dict[str, JsonOutput]
type JsonArray = list[JsonOutput]

__all__: tuple[str, ...] = (
    "Environment",
    "JsonArray",
    "JsonInput",
    "JsonObject",
    "JsonOutput",
    "JsonPrimitive",
    "Runtime",
    "RuntimeOptions",
    "Script",
)
