import {
  StrictMode,
  useEffect,
  useRef,
  useState,
  type ComponentType,
  type ReactNode,
} from "react";
import { createRoot, type Root } from "react-dom/client";
import {
  App,
  type AppEventMap,
  type AppOptions,
  type McpUiAppCapabilities,
} from "@modelcontextprotocol/ext-apps";
import {
  WidgetContext,
  activateWidget,
  deactivateWidget,
  useWidget,
  type WidgetToolLifecycle,
} from "./widget-context";

export {
  downloadFile,
  openLink,
  requestDisplayMode,
  requestTeardown,
  sendLog,
  sendMessage,
  updateModelContext,
} from "./app";

export {
  McpToolCancelledError,
  McpToolError,
  type McpToolErrorResult,
  type RawToolResult,
  type ToolCallError,
  type ToolCallResult,
} from "./tool-error";

export {
  useToolResult,
  type ToolResultState,
  type ToolResultStatus,
} from "./use-tool-result";

export { useWidget };

export type WidgetMetadata = {
  name: string;
  version: string;
  title?: string;
  capabilities?: McpUiAppCapabilities;
} & Pick<AppOptions, "autoResize" | "strict">;

export type WidgetHooks = {
  before?: () => void | Promise<void>;
  after?: () => void | Promise<void>;
  error?: (error: Error) => void;
  toolInput?: (params: AppEventMap["toolinput"]) => void;
  toolInputPartial?: (params: AppEventMap["toolinputpartial"]) => void;
  toolResult?: (params: AppEventMap["toolresult"]) => void;
  toolCancelled?: (params: AppEventMap["toolcancelled"]) => void;
  hostContextChanged?: (params: AppEventMap["hostcontextchanged"]) => void;
  teardown?: NonNullable<App["onteardown"]>;
};

export type WidgetProps = {
  metadata: WidgetMetadata;
  children: ReactNode;
  hooks?: WidgetHooks;
  fallback?: ReactNode;
  error?: ReactNode | ((error: Error) => ReactNode);
};

function applyHooks(app: App, hooks: WidgetHooks | undefined): void {
  app.onerror = hooks?.error ?? ((error) => console.error(error));
  if (!hooks) {
    return;
  }
  if (hooks.toolInput) {
    app.addEventListener("toolinput", hooks.toolInput);
  }
  if (hooks.toolInputPartial) {
    app.addEventListener("toolinputpartial", hooks.toolInputPartial);
  }
  if (hooks.toolResult) {
    app.addEventListener("toolresult", hooks.toolResult);
  }
  if (hooks.toolCancelled) {
    app.addEventListener("toolcancelled", hooks.toolCancelled);
  }
  if (hooks.hostContextChanged) {
    app.addEventListener("hostcontextchanged", hooks.hostContextChanged);
  }
}

function initialToolLifecycle(): WidgetToolLifecycle {
  return {
    input: undefined,
    inputReceived: false,
    rawResult: undefined,
    cancellationReason: undefined,
    status: "pending",
    version: 0,
  };
}

let rootInstance: Root | null = null;

export function Widget({
  metadata,
  children,
  hooks,
  fallback,
  error: errorUI,
}: WidgetProps) {
  const [connected, setConnected] = useState(false);
  const [error, setError] = useState<Error | null>(null);
  const [toolLifecycle, setToolLifecycle] = useState(initialToolLifecycle);
  const appRef = useRef<App | null>(null);
  const initRef = useRef<{ metadata: WidgetMetadata; hooks: WidgetHooks | undefined } | null>(
    null,
  );
  if (initRef.current == null) {
    initRef.current = { metadata, hooks };
  }

  useEffect(() => {
    let cancelled = false;
    let active = false;
    const { metadata: meta, hooks: initHooks } = initRef.current!;
    const { capabilities, autoResize, strict, name, version, title } = meta;
    const options: AppOptions = {};
    if (autoResize !== undefined) {
      options.autoResize = autoResize;
    }
    if (strict !== undefined) {
      options.strict = strict;
    }
    const app = new App(
      title === undefined ? { name, version } : { name, version, title },
      capabilities ?? {},
      options,
    );
    appRef.current = app;
    setToolLifecycle(initialToolLifecycle());
    app.addEventListener("toolinput", (params) => {
      if (!cancelled) {
        setToolLifecycle((current) => ({
          ...current,
          input: params.arguments,
          inputReceived: true,
        }));
      }
    });
    app.addEventListener("toolresult", (params) => {
      if (!cancelled) {
        setToolLifecycle((current) => ({
          ...current,
          rawResult: params,
          cancellationReason: undefined,
          status: "result",
          version: current.version + 1,
        }));
      }
    });
    app.addEventListener("toolcancelled", (params) => {
      if (!cancelled) {
        setToolLifecycle((current) => ({
          ...current,
          rawResult: undefined,
          cancellationReason: params.reason,
          status: "cancelled",
          version: current.version + 1,
        }));
      }
    });
    applyHooks(app, initHooks);
    app.onteardown = async (params, extra) => {
      if (active) {
        deactivateWidget(app);
        active = false;
      }
      return (await initHooks?.teardown?.(params, extra)) ?? {};
    };

    void (async () => {
      try {
        await initHooks?.before?.();
        if (cancelled) {
          return;
        }
        try {
          await app.connect();
        } catch (err: unknown) {
          if (!(err instanceof Error && err.message.includes("already connected"))) {
            throw err;
          }
        }
        if (cancelled) {
          return;
        }
        activateWidget(app);
        active = true;
        await initHooks?.after?.();
        if (!cancelled) {
          setConnected(true);
        } else {
          deactivateWidget(app);
          active = false;
        }
      } catch (err: unknown) {
        if (active) {
          deactivateWidget(app);
          active = false;
        }
        if (!cancelled) {
          setError(err instanceof Error ? err : new Error(String(err)));
        }
      }
    })();

    return () => {
      cancelled = true;
      if (active) {
        deactivateWidget(app);
        active = false;
      }
      void app.close();
      if (appRef.current === app) {
        appRef.current = null;
      }
    };
  }, []);

  if (error) {
    if (typeof errorUI === "function") return errorUI(error);
    if (errorUI !== undefined) return errorUI;
    return (
      <div>
        <strong>ERROR:</strong> {error.message}
      </div>
    );
  }
  if (!connected || appRef.current == null) {
    return fallback ?? <div>Connecting...</div>;
  }

  return (
    <WidgetContext.Provider
      value={{ app: appRef.current, tool: toolLifecycle }}
    >
      {children}
    </WidgetContext.Provider>
  );
}

export function mountWidget(Widget: ComponentType): void {
  if (!rootInstance) {
    const element = document.querySelector("#root");
    if (!(element instanceof HTMLElement)) {
      throw new Error("Widget root #root was not found");
    }
    rootInstance = createRoot(element);
  }

  rootInstance.render(
    <StrictMode>
      <Widget />
    </StrictMode>,
  );
}
