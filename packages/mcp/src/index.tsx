import {
  StrictMode,
  createContext,
  useContext,
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

export type BelgieMetadata = {
  name: string;
  version: string;
  title?: string;
  capabilities?: McpUiAppCapabilities;
} & Pick<AppOptions, "autoResize" | "strict">;

export type BelgieHooks = {
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

export type BelgieProps = {
  metadata: BelgieMetadata;
  children: ReactNode;
  hooks?: BelgieHooks;
  fallback?: ReactNode;
  error?: ReactNode | ((error: Error) => ReactNode);
};

const BelgieAppContext = createContext<App | null>(null);

export function useApp(): App {
  const app = useContext(BelgieAppContext);
  if (app == null) {
    throw new Error("useApp must be used within a connected <Belgie>");
  }
  return app;
}

function applyHooks(app: App, hooks: BelgieHooks | undefined): void {
  if (!hooks) {
    return;
  }
  if (hooks.error) {
    app.onerror = hooks.error;
  }
  if (hooks.toolInput) {
    app.ontoolinput = hooks.toolInput;
  }
  if (hooks.toolInputPartial) {
    app.ontoolinputpartial = hooks.toolInputPartial;
  }
  if (hooks.toolResult) {
    app.ontoolresult = hooks.toolResult;
  }
  if (hooks.toolCancelled) {
    app.ontoolcancelled = hooks.toolCancelled;
  }
  if (hooks.hostContextChanged) {
    app.onhostcontextchanged = hooks.hostContextChanged;
  }
  if (hooks.teardown) {
    app.onteardown = hooks.teardown;
  }
}

let rootInstance: Root | null = null;

export function Belgie({
  metadata,
  children,
  hooks,
  fallback,
  error: errorUI,
}: BelgieProps) {
  const [connected, setConnected] = useState(false);
  const [error, setError] = useState<Error | null>(null);
  const appRef = useRef<App | null>(null);
  const initRef = useRef<{ metadata: BelgieMetadata; hooks: BelgieHooks | undefined } | null>(
    null,
  );
  if (initRef.current == null) {
    initRef.current = { metadata, hooks };
  }

  useEffect(() => {
    let cancelled = false;
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
    applyHooks(app, initHooks);

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
        await initHooks?.after?.();
        if (!cancelled) {
          setConnected(true);
        }
      } catch (err: unknown) {
        if (!cancelled) {
          setError(err instanceof Error ? err : new Error(String(err)));
        }
      }
    })();

    return () => {
      cancelled = true;
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
    <BelgieAppContext.Provider value={appRef.current}>{children}</BelgieAppContext.Provider>
  );
}

export function mountWidget(Widget: ComponentType): void {
  if (!rootInstance) {
    const element = document.querySelector("#root");
    if (!(element instanceof HTMLElement)) {
      throw new Error("Belgie widget root #root was not found");
    }
    rootInstance = createRoot(element);
  }

  rootInstance.render(
    <StrictMode>
      <Widget />
    </StrictMode>,
  );
}
