import { useTheme, useWidget } from "@belgie/mcp";
import { OpenAIExtensions } from "@openai/mcp-extensions/app";
import { useEffect, useMemo, useReducer } from "react";

type OpenAIApp = ConstructorParameters<typeof OpenAIExtensions>[0];

// One OpenAI extension surface per connected app. Its getters read host context, so re-render
// Whenever the host pushes a change such as a new deep link or cleared model context.
export function useOpenAI(): OpenAIExtensions {
  const app = useWidget();
  // @openai/mcp-extensions pins zod, so the package manager resolves its own copy of the ext-apps
  // Types. It uses `App` only as a type, so the connected app is safe to pass across the copies.
  const openai = useMemo(() => new OpenAIExtensions(app as unknown as OpenAIApp), [app]);
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
