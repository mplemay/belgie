import { execFile } from "node:child_process";
import { promisify } from "node:util";

import { BelgieJavaScriptError, BelgieModuleError, BelgieRuntimeError, Runtime, Script } from "../src/index.ts";

const execFileAsync = promisify(execFile);

describe("sandbox runtime", () => {
  it("runs typed TypeScript and preserves module state", async () => {
    await using runtime = await Runtime.create({ maxWorkers: 1 });
    const script = new Script<[number], { calls: number; doubled: number }>(`
      let calls = 0;
      export default function run(value: number) {
        return { calls: ++calls, doubled: value * 2 };
      }
    `);
    await using runner = await runtime.bind(script);

    await expect(runner.run(21)).resolves.toStrictEqual({ calls: 1, doubled: 42 });
    await expect(runner.run(10)).resolves.toStrictEqual({ calls: 2, doubled: 20 });
  });

  it("serializes concurrent calls in invocation order", async () => {
    await using runtime = await Runtime.create();
    await using runner = await runtime.bind(
      new Script<[string], { order: number; value: string }>(`
        let order = 0;
        export async function run(value: string) {
          await Promise.resolve();
          return { order: ++order, value };
        }
      `),
    );

    await expect(Promise.all([runner.run("first"), runner.run("second"), runner.run("third")])).resolves.toStrictEqual([
      { order: 1, value: "first" },
      { order: 2, value: "second" },
      { order: 3, value: "third" },
    ]);
  });

  it("keeps runners independent and resets reused workers", async () => {
    await using runtime = await Runtime.create({ maxWorkers: 2 });
    const script = new Script<[], number>("let value = 0; export default () => ++value;");
    const first = await runtime.bind(script);
    const second = await runtime.bind(script);

    await expect(first.run()).resolves.toBe(1);
    await expect(first.run()).resolves.toBe(2);
    await expect(second.run()).resolves.toBe(1);
    await first.close();
    await second.close();

    await using reused = await runtime.bind(script);
    await expect(reused.run()).resolves.toBe(1);
  });

  it("rejects imports and missing exports as module errors", async () => {
    await using runtime = await Runtime.create();

    expect(() => new Script("import './dependency.ts'; export default () => null;")).toThrow(
      expect.objectContaining({
        code: "imports_disabled",
        name: "BelgieModuleError",
      }),
    );
    expect(() => new Script("export default () => import('./dependency.ts');")).toThrow(BelgieModuleError);
    expect(() => new Script("export default () => <main>Hello</main>;")).toThrow(BelgieModuleError);
    await expect(runtime.bind(new Script("export const value = 1;"))).rejects.toBeInstanceOf(BelgieModuleError);
  });

  it("exposes no host globals", async () => {
    await using runtime = await Runtime.create();
    await using runner = await runtime.bind(
      new Script<[], Record<string, string>>(`
        export default () => ({
          Deno: typeof Deno,
          WebAssembly: typeof WebAssembly,
          console: typeof console,
          process: typeof process,
          queueMicrotask: typeof queueMicrotask,
          require: typeof require,
          setTimeout: typeof setTimeout,
        });
      `),
    );

    await expect(runner.run()).resolves.toStrictEqual({
      Deno: "undefined",
      WebAssembly: "undefined",
      console: "undefined",
      process: "undefined",
      queueMicrotask: "undefined",
      require: "undefined",
      setTimeout: "undefined",
    });
  });

  it("maps JavaScript and unsupported result errors", async () => {
    await using runtime = await Runtime.create();
    await using throwing = await runtime.bind(new Script("export default () => { throw new Error('nope'); };"));
    await expect(throwing.run()).rejects.toBeInstanceOf(BelgieJavaScriptError);

    await using unsupported = await runtime.bind(new Script("export default () => 1n;"));
    await expect(unsupported.run()).rejects.toBeInstanceOf(TypeError);
  });

  it("rejects unsupported arguments before native execution", async () => {
    await using runtime = await Runtime.create();
    await using runner = await runtime.bind(new Script<[unknown], null>("export default () => null;"));

    await expect(runner.run(undefined)).rejects.toBeInstanceOf(TypeError);
    await expect(runner.run(1n)).rejects.toBeInstanceOf(TypeError);
    await expect(runner.run(Number.NaN)).rejects.toBeInstanceOf(TypeError);
    await expect(runner.run(new Date())).rejects.toBeInstanceOf(TypeError);
    const cycle: unknown[] = [];
    cycle.push(cycle);
    await expect(runner.run(cycle)).rejects.toBeInstanceOf(TypeError);
    await expect(runner.run(new Proxy({}, {}))).rejects.toBeInstanceOf(TypeError);
  });

  it("enforces checkout timeouts", async () => {
    await using runtime = await Runtime.create({
      checkoutTimeoutMs: 50,
      maxWorkers: 1,
    });
    await using runner = await runtime.bind(new Script("export default () => true;"));
    void runner;

    await expect(runtime.bind(new Script("export default () => false;"))).rejects.toMatchObject({
      code: "checkout_timeout",
    });
  });

  it("kills timed out workers and supplies a healthy replacement", async () => {
    await using runtime = await Runtime.create({
      maxWorkers: 1,
      runTimeoutMs: 100,
    });
    const stuck = await runtime.bind(new Script("export default () => { while (true) {} };"));

    await expect(stuck.run()).rejects.toMatchObject({ code: "run_timeout" });
    await expect(stuck.run()).rejects.toMatchObject({ code: "runtime_closed" });

    await using healthy = await runtime.bind(
      new Script<[number], number>("export default (value: number) => value * 2;"),
    );
    await expect(healthy.run(21)).resolves.toBe(42);
  });

  it("contains V8 heap failures to one worker", async () => {
    await using runtime = await Runtime.create({
      maxOldGenerationSizeMb: 32,
      maxWorkers: 1,
      runTimeoutMs: 5000,
    });
    const exhausted = await runtime.bind(
      new Script(`
        export default () => {
          const values = [];
          while (true) values.push(new Array(250_000).fill("memory"));
        };
      `),
    );

    await expect(exhausted.run()).rejects.toMatchObject({
      code: "worker_crash",
    });
    await using healthy = await runtime.bind(new Script("export default () => 42;"));
    await expect(healthy.run()).resolves.toBe(42);
  });

  it("discards a worker when closed during execution", async () => {
    await using runtime = await Runtime.create({
      maxWorkers: 1,
      runTimeoutMs: 5000,
    });
    const runner = await runtime.bind(new Script("export default () => { while (true) {} };"));
    const invocation = runner.run();
    await new Promise((resolve) => setImmediate(resolve));
    await runner.close();

    await expect(invocation).rejects.toBeInstanceOf(BelgieRuntimeError);
    await using healthy = await runtime.bind(new Script("export default () => 'healthy';"));
    await expect(healthy.run()).resolves.toBe("healthy");
  });

  it("terminates active runners when the runtime closes", async () => {
    const runtime = await Runtime.create({ runTimeoutMs: 5000 });
    const runner = await runtime.bind(new Script("export default () => { while (true) {} };"));
    const invocation = runner.run();
    await new Promise((resolve) => setImmediate(resolve));

    await runtime.close();
    await expect(invocation).rejects.toBeInstanceOf(BelgieRuntimeError);
    await expect(runner.run()).rejects.toMatchObject({ code: "runtime_closed" });
  });

  it("invalidates runners when the runtime closes", async () => {
    const runtime = await Runtime.create();
    const runner = await runtime.bind(new Script("export default () => 1;"));

    await runtime.close();
    await runtime.close();
    await expect(runner.run()).rejects.toMatchObject({ code: "runtime_closed" });
    await expect(runtime.bind(new Script("export default () => 2;"))).rejects.toMatchObject({ code: "runtime_closed" });
  });

  it("does not panic when Node exits after runtime disposal", async () => {
    const program = `
      import { Runtime, Script } from "./dist/index.js";
      const runtime = await Runtime.create();
      const runner = await runtime.bind(new Script("export default () => 42;"));
      console.log(await runner.run());
      await runtime.close();
    `;
    const result = await execFileAsync(process.execPath, ["--input-type=module", "--eval", program], {
      cwd: new URL("..", import.meta.url),
      timeout: 5000,
    });
    expect(result.stdout.trim()).toBe("42");
    expect(result.stderr).toBe("");
  });
});
