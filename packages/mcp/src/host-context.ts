import type { App, AppEventMap, McpUiDisplayMode, McpUiHostContext, McpUiTheme } from "@modelcontextprotocol/ext-apps";
import { useCallback, useMemo, useSyncExternalStore } from "react";

import { useConnectedWidgetContext } from "./widget-context";

export type SafeAreaInsets = NonNullable<McpUiHostContext["safeAreaInsets"]>;

export interface SafeArea {
  insets: SafeAreaInsets;
}

export interface LayoutState {
  maxHeight: number | undefined;
  safeArea: SafeArea;
}

export type DeviceType = "mobile" | "tablet" | "desktop" | "unknown";

export interface UserAgent {
  device: {
    type: DeviceType;
  };
  capabilities: {
    hover: boolean;
    touch: boolean;
  };
}

const DEFAULT_LOCALE = "en-US";
const DEFAULT_SAFE_AREA_INSETS: SafeAreaInsets = {
  top: 0,
  right: 0,
  bottom: 0,
  left: 0,
};

function useHostContextValue<K extends keyof McpUiHostContext>(app: App, key: K): McpUiHostContext[K] {
  const subscribe = useCallback(
    (onChange: () => void) => {
      const handleHostContextChanged = (params: AppEventMap["hostcontextchanged"]) => {
        if (key in params) {
          onChange();
        }
      };

      app.addEventListener("hostcontextchanged", handleHostContextChanged);
      return () => {
        app.removeEventListener("hostcontextchanged", handleHostContextChanged);
      };
    },
    [app, key],
  );
  const getSnapshot = useCallback(() => app.getHostContext()?.[key], [app, key]);

  return useSyncExternalStore(subscribe, getSnapshot, getSnapshot);
}

function useMaxHeight(app: App): number | undefined {
  const subscribe = useCallback(
    (onChange: () => void) => {
      const handleHostContextChanged = (params: AppEventMap["hostcontextchanged"]) => {
        if ("containerDimensions" in params) {
          onChange();
        }
      };

      app.addEventListener("hostcontextchanged", handleHostContextChanged);
      return () => {
        app.removeEventListener("hostcontextchanged", handleHostContextChanged);
      };
    },
    [app],
  );
  const getSnapshot = useCallback(() => {
    const containerDimensions = app.getHostContext()?.containerDimensions;
    return containerDimensions !== undefined && "maxHeight" in containerDimensions
      ? containerDimensions.maxHeight
      : undefined;
  }, [app]);

  return useSyncExternalStore(subscribe, getSnapshot, getSnapshot);
}

function normalizeLocale(locale: string): string {
  try {
    return new Intl.Locale(locale.replaceAll("_", "-")).toString();
  } catch {
    return DEFAULT_LOCALE;
  }
}

export function useDisplayMode() {
  const { app } = useConnectedWidgetContext("useDisplayMode");
  const displayMode = useHostContextValue(app, "displayMode") ?? "inline";
  const setDisplayMode = useCallback((mode: McpUiDisplayMode) => app.requestDisplayMode({ mode }), [app]);

  return [displayMode, setDisplayMode] as const;
}

export function useLayout(): LayoutState {
  const { app } = useConnectedWidgetContext("useLayout");
  const maxHeight = useMaxHeight(app);
  const safeAreaInsets = useHostContextValue(app, "safeAreaInsets");
  const safeArea = useMemo(() => ({ insets: safeAreaInsets ?? DEFAULT_SAFE_AREA_INSETS }), [safeAreaInsets]);

  return useMemo(() => ({ maxHeight, safeArea }), [maxHeight, safeArea]);
}

export function useLocale(): string {
  const { app } = useConnectedWidgetContext("useLocale");
  const locale = useHostContextValue(app, "locale") ?? DEFAULT_LOCALE;

  return normalizeLocale(locale);
}

export function useTheme(): McpUiTheme {
  const { app } = useConnectedWidgetContext("useTheme");

  return useHostContextValue(app, "theme") ?? "light";
}

export function useUserAgent(): UserAgent {
  const { app } = useConnectedWidgetContext("useUserAgent");
  const platform = useHostContextValue(app, "platform");
  const deviceCapabilities = useHostContextValue(app, "deviceCapabilities");

  return useMemo(
    () => ({
      device: {
        type: platform === "web" ? "desktop" : (platform ?? "unknown"),
      },
      capabilities: {
        hover: deviceCapabilities?.hover ?? true,
        touch: deviceCapabilities?.touch ?? true,
      },
    }),
    [deviceCapabilities, platform],
  );
}
