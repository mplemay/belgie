# `@belgie/runtime`

Private, current-platform prototype for running inline JavaScript and TypeScript in crash-isolated worker processes.

```ts
import { Runtime, Script } from "@belgie/runtime";

await using runtime = await Runtime.create();
const script = new Script<[number], { doubled: number }>(`
  export default function run(value: number) {
    return { doubled: value * 2 };
  }
`);
await using runner = await runtime.bind(script);

console.log(await runner.run(21));
```

`Runtime` owns an elastic subprocess pool. A bound `Runner` has exclusive use of one worker, preserves module state
between calls, and returns that worker only after a clean close. Runs on one runner execute in invocation order. Closing
a runtime closes its runners and workers; both lifecycle classes also implement `Symbol.asyncDispose`.

The sandbox exposes ECMAScript built-ins, promises, top-level await, and TypeScript type erasure. It deliberately
exposes no imports, TSX, packages, `Deno`, Node globals, filesystem, environment, network, subprocess, FFI, timers,
console, or host callbacks. Arguments and results must be JSON values and may be nested at most 64 levels.

Worker processes contain V8 crashes and enforce run timeouts. They are not an OS security boundary, and the V8
old-generation limit is not a hard total-process memory limit. This prototype is private, supports only the locally
built platform, and has no publishing or release automation.
