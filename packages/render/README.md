# `@belgie/render`

`@belgie/render` bundles an inline React widget entirely inside Belgie's secure Deno `run_code` runtime and returns one
self-contained HTML document.

```tsx
import { render } from "npm:@belgie/render";

function Widget() {
  return <main>Hello from Belgie</main>;
}

export default function run() {
  return render({
    widget: <Widget />,
    plugins: [],
  });
}
```

The source must be a single inline TSX module. Package imports are supported, but relative host-file imports are
intentionally unavailable. `plugins` are executed during the server-side Vite build and removed from the browser module
graph.
