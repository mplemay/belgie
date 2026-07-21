import { render } from "@belgie/render";
import type { RenderOptions } from "@belgie/render";
import type { Plugin } from "vite";

const plugin: Plugin = { name: "example" };
const options = { plugins: [plugin], widget: <main>Hello</main> } satisfies RenderOptions;
const html: Promise<string> = render(options);

void html;
