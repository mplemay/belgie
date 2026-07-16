import path from "node:path";
import { fileURLToPath } from "node:url";

import { belgie } from "@belgie/mcp/vite";
import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

const viewsDir = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  "src/shadcn/views",
);
const widgetsDir = path.resolve(viewsDir, "widgets");

export default defineConfig({
  plugins: [belgie({ srcDir: "src/shadcn/views/widgets" }), react(), tailwindcss()],
  resolve: {
    alias: {
      "@widgets": widgetsDir,
      "@": viewsDir,
    },
  },
});
