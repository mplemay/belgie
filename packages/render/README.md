# `@belgie/render`

`@belgie/render` returns a render request from agent `run_code` Scripts. `BelgieRuntimeSession` (and
the Pydantic AI / LangChain toolsets) complete that request on a Belgie-owned renderer side-channel
and return one self-contained HTML document. Model-visible Scripts stay workspace-restricted: they
do not receive host `/etc`/`/proc`, `allow_sys`, or `allow_ffi`, even when inline rendering is
available. The renderer uses workspace-scoped read/write/FFI and limited `allow_sys` for Vite native
loaders — not host path grants.

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

The source must be a single inline TSX module. Package imports are supported. Relative imports are
unsupported for the browser widget graph; server `plugins` may import workspace modules, resolved
like Deno from the inline module URL (`__deno_python_inline__.tsx` in the Environment workspace).

`plugins` run only during the server-side Vite build on the privileged renderer. Script-side `plugins` expressions
still evaluate under workspace-only permissions and are discarded; the privileged rebuild from source evaluates the
plugin expression again. Plugin factories, hooks, and their imports therefore run with the renderer's broader
permissions. Treat plugins as reviewed application code and use `plugins: []` for untrusted agents. Prefer pure
factories or relative workspace plugin modules when construction must succeed in the restricted Script. Both
`plugins` and `widget` must appear in a statically analyzable `render(...)` options object
(inline literal, variable binding, or static object spread). Computed option keys, opaque spreads, and
post-declaration mutation are unsupported and throw instead of shipping unsafe code to the browser. The browser
mounts the extracted `widget` expression and does not re-execute `run()`, so side effects inside `run()` stay
server-only. Widget expressions may only reference module-level bindings.

Hosts that manage their own `Runtime` (without `BelgieRuntimeSession`) should call
`buildFromSource` from `@belgie/render/host` on a worker with workspace FFI/sys grants; importing that
entry from a restricted Script would reintroduce Vite's native grants into the model-visible session.
