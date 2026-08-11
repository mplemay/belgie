import { createRequire } from "node:module";
import { resolve } from "node:path";

export interface NativeRuntimeOptions {
  checkoutTimeoutMs: number;
  maxOldGenerationSizeMb: number;
  maxWorkers: number;
  minWorkers: number;
  runTimeoutMs: number;
  workerPath: string;
}

export interface NativeRunner {
  close: () => Promise<void>;
  run: (argumentsJson: string) => Promise<string>;
}

export interface NativeRuntime {
  bind: (source: string) => Promise<NativeRunner>;
  close: () => Promise<void>;
}

interface NativeRuntimeConstructor {
  create: (options: NativeRuntimeOptions) => Promise<NativeRuntime>;
}

interface NativeBinding {
  NativeRuntime: NativeRuntimeConstructor;
}

const moduleDirectory = import.meta.dirname;
const nativeDirectory = resolve(moduleDirectory, "../native");
const require = createRequire(import.meta.url);
const binding = require("../native/belgie_runtime_binding.node") as NativeBinding;

export const NativeRuntime = binding.NativeRuntime;
export const workerPath = resolve(
  nativeDirectory,
  process.platform === "win32" ? "belgie-runtime-worker.exe" : "belgie-runtime-worker",
);
