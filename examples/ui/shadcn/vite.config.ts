import path from "node:path";
import { fileURLToPath } from "node:url";

import { belgie } from "@belgie/mcp/vite";
import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

const srcDir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "src");

export default defineConfig({
  plugins: [belgie(), react(), tailwindcss()],
  resolve: {
    alias: {
      "@": srcDir,
    },
  },
});
