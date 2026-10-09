import { useTheme, useWidget } from "@belgie/mcp";
import { OpenAIExtensions } from "@openai/mcp-extensions/app";
import { useEffect, useMemo, useReducer } from "react";

type OpenAIApp = ConstructorParameters<typeof OpenAIExtensions>[0];

// @openai/mcp-extensions pins zod, so its ext-apps types can resolve to a separate copy.
// The SDK uses `App` only as a type, so the connected app is safe to pass across the copies.
function asOpenAIApp(app: unknown): OpenAIApp {
  return app as OpenAIApp;
}

// One OpenAI extension surface per connected app.
// Its getters read host context, so re-render on host changes such as a new deep link.
export function useOpenAI(): OpenAIExtensions {
  const app = useWidget();
  const openai = useMemo(() => new OpenAIExtensions(asOpenAIApp(app)), [app]);
  const [, rerender] = useReducer((count: number) => count + 1, 0);
  const theme = useTheme();

  useEffect(() => {
    app.addEventListener("hostcontextchanged", rerender);
    return () => {
      app.removeEventListener("hostcontextchanged", rerender);
    };
  }, [app]);

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
  }, [theme]);

  return openai;
}
