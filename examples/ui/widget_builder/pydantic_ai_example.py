from pathlib import Path
from typing import Any, Final

from pydantic_ai import Agent
from pydantic_ai.messages import ToolReturnPart

from belgie.pydantic_ai import BelgieCapability
from belgie.widget import WidgetBuilder, WidgetBundle

EXAMPLE_DIR: Final[Path] = Path(__file__).parent


def project_prompt() -> str:
    widget = (EXAMPLE_DIR / "widget.tsx").read_text(encoding="utf-8")
    component = (EXAMPLE_DIR / "weather-card.tsx").read_text(encoding="utf-8")
    styles = (EXAMPLE_DIR / "styles.css").read_text(encoding="utf-8")
    return f"""Call build_widget once with this virtual project.

widget.tsx:
```tsx
{widget}
```

weather-card.tsx:
```tsx
{component}
```

styles.css:
```css
{styles}
```
"""


def widget_artifacts(messages: list[Any]) -> list[WidgetBundle]:
    return [
        metadata["widget"]
        for message in messages
        for part in message.parts
        if isinstance(part, ToolReturnPart)
        and isinstance(part.metadata, dict)
        and isinstance(metadata := part.metadata, dict)
        and isinstance(metadata.get("widget"), WidgetBundle)
    ]


agent = Agent(
    "openai:gpt-5",
    capabilities=[BelgieCapability(widget_builder=WidgetBuilder())],
)
result = agent.run_sync(project_prompt())
bundle = widget_artifacts(result.new_messages())[0]
print(bundle.html)  # noqa: T201
