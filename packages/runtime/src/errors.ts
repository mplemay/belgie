export type BelgieRuntimeErrorCode =
  | "checkout_timeout"
  | "invalid_options"
  | "protocol_failure"
  | "run_timeout"
  | "runtime_closed"
  | "worker_crash"
  | "worker_spawn";

export class BelgieError extends Error {
  readonly code: string;

  constructor(message: string, code: string, options?: ErrorOptions) {
    super(message, options);
    this.code = code;
    this.name = "BelgieError";
  }
}

export class BelgieRuntimeError extends BelgieError {
  declare readonly code: BelgieRuntimeErrorCode;

  constructor(message: string, code: BelgieRuntimeErrorCode, options?: ErrorOptions) {
    super(message, code, options);
    this.name = "BelgieRuntimeError";
  }
}

export class BelgieModuleError extends BelgieError {
  constructor(message: string, code: string, options?: ErrorOptions) {
    super(message, code, options);
    this.name = "BelgieModuleError";
  }
}

export class BelgieJavaScriptError extends BelgieError {
  constructor(message: string, code: string, options?: ErrorOptions) {
    super(message, code, options);
    this.name = "BelgieJavaScriptError";
  }
}

interface NativeErrorPayload {
  code: string;
  kind: "javascript" | "module" | "runtime" | "value";
  message: string;
}

const ERROR_PREFIX = "BELGIE_ERROR:";

export function mapNativeError(error: unknown): Error {
  if (!(error instanceof Error)) {
    return new BelgieRuntimeError("An unknown native runtime error occurred", "protocol_failure");
  }
  const marker = error.message.indexOf(ERROR_PREFIX);
  if (marker === -1) {
    return new BelgieRuntimeError(error.message, "protocol_failure", {
      cause: error,
    });
  }
  try {
    const payload = JSON.parse(error.message.slice(marker + ERROR_PREFIX.length)) as NativeErrorPayload;
    switch (payload.kind) {
      case "module": {
        return new BelgieModuleError(payload.message, payload.code, {
          cause: error,
        });
      }
      case "javascript": {
        return new BelgieJavaScriptError(payload.message, payload.code, {
          cause: error,
        });
      }
      case "value": {
        return new TypeError(payload.message, { cause: error });
      }
      case "runtime": {
        return new BelgieRuntimeError(payload.message, asRuntimeCode(payload.code), { cause: error });
      }
      default: {
        return new BelgieRuntimeError(error.message, "protocol_failure", {
          cause: error,
        });
      }
    }
  } catch {
    return new BelgieRuntimeError(error.message, "protocol_failure", {
      cause: error,
    });
  }
}

function asRuntimeCode(code: string): BelgieRuntimeErrorCode {
  switch (code) {
    case "checkout_timeout":
    case "invalid_options":
    case "protocol_failure":
    case "run_timeout":
    case "runtime_closed":
    case "worker_crash":
    case "worker_spawn": {
      return code;
    }
    default: {
      return "protocol_failure";
    }
  }
}
