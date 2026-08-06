import { belgie } from "@belgie/vite";
import type { BelgiePluginOptions } from "@belgie/vite";
import type { Plugin } from "vite";

const options = { srcDir: "src/widgets", bundle: "inline" } satisfies BelgiePluginOptions;
const plugin: Plugin = belgie(options);

void plugin;
