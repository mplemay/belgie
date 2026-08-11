import { availableParallelism } from "node:os";

import { BelgieRuntimeError, mapNativeError } from "./errors.ts";
import { NativeRuntime, workerPath } from "./native.ts";
import type { NativeRunner, NativeRuntime as NativeRuntimeInstance } from "./native.ts";
import { validateScriptSource } from "./script.ts";
import { serializeArguments } from "./value.ts";
import type { JsonValue } from "./value.ts";

export {
  BelgieError,
  BelgieJavaScriptError,
  BelgieModuleError,
  BelgieRuntimeError,
  type BelgieRuntimeErrorCode,
} from "./errors.ts";
export type { JsonPrimitive, JsonValue } from "./value.ts";

export interface RuntimeOptions {
  checkoutTimeoutMs?: number;
  maxOldGenerationSizeMb?: number;
  maxWorkers?: number;
  minWorkers?: number;
  runTimeoutMs?: number;
}

interface NormalizedRuntimeOptions {
  checkoutTimeoutMs: number;
  maxOldGenerationSizeMb: number;
  maxWorkers: number;
  minWorkers: number;
  runTimeoutMs: number;
}

export class Script<Args extends readonly unknown[] = JsonValue[], Result = JsonValue> {
  readonly source: string;
  declare private readonly __args?: Args;
  declare private readonly __result?: Result;

  constructor(source: string) {
    if (typeof source !== "string" || source.trim().length === 0) {
      throw new TypeError("Script source must be a non-empty string");
    }
    validateScriptSource(source);
    this.source = source;
  }
}

export class Runtime {
  readonly #native: NativeRuntimeInstance;
  readonly #runners = new Set<Runner<readonly unknown[], unknown>>();
  #closed = false;

  private constructor(native: NativeRuntimeInstance) {
    this.#native = native;
  }

  static async create(options: RuntimeOptions = {}): Promise<Runtime> {
    const normalized = normalizeOptions(options);
    try {
      const native = await NativeRuntime.create({
        ...normalized,
        workerPath,
      });
      return new Runtime(native);
    } catch (error) {
      throw mapNativeError(error);
    }
  }

  async bind<Args extends readonly unknown[], Result>(script: Script<Args, Result>): Promise<Runner<Args, Result>> {
    this.#assertOpen();
    if (!(script instanceof Script)) {
      throw new TypeError("Runtime.bind() requires a Script instance");
    }
    try {
      const native = await this.#native.bind(script.source);
      if (this.#closed) {
        await native.close();
        throw new BelgieRuntimeError("Runtime is closed", "runtime_closed");
      }
      const runner = new Runner<Args, Result>(native, (closedRunner) => {
        this.#runners.delete(closedRunner as Runner<readonly unknown[], unknown>);
      });
      this.#runners.add(runner as Runner<readonly unknown[], unknown>);
      return runner;
    } catch (error) {
      if (error instanceof BelgieRuntimeError) {
        throw error;
      }
      throw mapNativeError(error);
    }
  }

  async close(): Promise<void> {
    if (this.#closed) {
      return;
    }
    this.#closed = true;
    const runners = [...this.#runners];
    this.#runners.clear();
    await Promise.allSettled(runners.map(async (runner) => runner.close()));
    try {
      await this.#native.close();
    } catch (error) {
      throw mapNativeError(error);
    }
  }

  async [Symbol.asyncDispose](): Promise<void> {
    await this.close();
  }

  #assertOpen(): void {
    if (this.#closed) {
      throw new BelgieRuntimeError("Runtime is closed", "runtime_closed");
    }
  }
}

export class Runner<Args extends readonly unknown[], Result> {
  readonly #native: NativeRunner;
  readonly #onClose: (runner: Runner<Args, Result>) => void;
  #closed = false;
  #queue: Promise<void> = Promise.resolve();

  constructor(native: NativeRunner, onClose: (runner: Runner<Args, Result>) => void) {
    this.#native = native;
    this.#onClose = onClose;
  }

  run(...arguments_: Args): Promise<Result> {
    let argumentsJson: string;
    try {
      this.#assertOpen();
      argumentsJson = serializeArguments(arguments_);
    } catch (error) {
      return Promise.reject(error);
    }
    const operation = this.#queue.then(async () => {
      this.#assertOpen();
      try {
        return JSON.parse(await this.#native.run(argumentsJson)) as Result;
      } catch (error) {
        throw mapNativeError(error);
      }
    });
    this.#queue = operation.then(
      () => undefined,
      () => undefined,
    );
    return operation;
  }

  async close(): Promise<void> {
    if (this.#closed) {
      return;
    }
    this.#closed = true;
    this.#onClose(this);
    try {
      await this.#native.close();
    } catch (error) {
      throw mapNativeError(error);
    }
  }

  async [Symbol.asyncDispose](): Promise<void> {
    await this.close();
  }

  #assertOpen(): void {
    if (this.#closed) {
      throw new BelgieRuntimeError("Runner is closed", "runtime_closed");
    }
  }
}

function normalizeOptions(options: RuntimeOptions): NormalizedRuntimeOptions {
  const normalized = {
    checkoutTimeoutMs: options.checkoutTimeoutMs ?? 30_000,
    maxOldGenerationSizeMb: options.maxOldGenerationSizeMb ?? 128,
    maxWorkers: options.maxWorkers ?? availableParallelism(),
    minWorkers: options.minWorkers ?? 1,
    runTimeoutMs: options.runTimeoutMs ?? 30_000,
  };
  for (const [name, value] of Object.entries(normalized)) {
    if (!Number.isSafeInteger(value) || value <= 0 || value > 4_294_967_295) {
      throw new TypeError(`${name} must be a positive 32-bit integer`);
    }
  }
  if (normalized.minWorkers > normalized.maxWorkers) {
    throw new TypeError("minWorkers must be less than or equal to maxWorkers");
  }
  return normalized;
}
