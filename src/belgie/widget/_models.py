from collections.abc import Mapping
from dataclasses import dataclass, field


@dataclass(slots=True, kw_only=True, frozen=True)
class WidgetSource:
    widget: str
    files: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "files", dict(self.files))


@dataclass(slots=True, kw_only=True, frozen=True)
class WidgetBundle:
    html: str
