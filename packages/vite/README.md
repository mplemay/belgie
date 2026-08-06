# `@belgie/vite`

Vite plugin and CLI for Belgie React widgets.

## Project mode

```ts
import { belgie } from "@belgie/vite";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [belgie({ srcDir: "src/widgets" })],
});
```

Widgets live at `<srcDir>/<name>/widget.tsx` and must default-export a React component.

## CLI mode

```bash
@belgie/vite --widget path/to/widget.tsx --out widget.html --plugins npm:@tailwindcss/vite@latest
```

From Belgie Python:

```python
await runtime(Command("@belgie/vite"))(
    "--widget",
    "path/to/widget.tsx",
    "--out",
    "widget.html",
    "--plugins",
    "npm:@tailwindcss/vite@latest",
)
```
