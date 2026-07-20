import type { Plugin } from "vite";

import { render, type RenderOptions } from "@belgie/render";

const plugin: Plugin = { name: "example" };
const options = { plugins: [plugin], widget: <main>Hello</main> } satisfies RenderOptions;
const html: Promise<string> = render(options);

void html;
