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
intentionally unavailable.

`plugins` run only during the server-side Vite build. Both `plugins` and `widget` must appear in a statically
analyzable `render(...)` options object (inline literal, variable binding, or static object spread). Computed option
keys, opaque spreads, and post-declaration mutation are unsupported and throw instead of shipping unsafe code to the
browser. The browser mounts the extracted `widget` expression and does not re-execute `run()`, so side effects inside
`run()` stay server-only. Widget expressions may only reference module-level bindings.
