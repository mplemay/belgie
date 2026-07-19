# Isolated widget builder

This example keeps `widget.tsx`, its local component, and CSS as an ordinary multi-file project while passing their text
to `build_widget` as virtual files. The trusted `WidgetBuilder` owns the dependency allowlist and compiler environment;
the model cannot install packages or create source files.

`pydantic_ai_example.py` extracts the resulting `WidgetBundle` from `ToolReturnPart.metadata`. The model sees only the
concise build summary. `langchain_example.py` extracts the same bundle from `ToolMessage.artifact`.

The checked-in TSX is illustrative and can also be built directly:

```python
from pathlib import Path

from belgie.widget import WidgetBuilder, WidgetSource

root = Path(__file__).parent
source = WidgetSource(
    widget=(root / "widget.tsx").read_text(),
    files={
        "WeatherCard.tsx": (root / "WeatherCard.tsx").read_text(),
        "styles.css": (root / "styles.css").read_text(),
    },
)

with WidgetBuilder() as builder:
    bundle = builder.build(source)
```
