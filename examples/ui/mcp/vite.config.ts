import path from "node:path";
import { fileURLToPath } from "node:url";

import { belgie } from "@belgie/mcp/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

const viewsDir = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  "src/mcp_app/views",
);
const widgetsDir = path.resolve(viewsDir, "widgets");

export default defineConfig({
  plugins: [belgie({ srcDir: "src/mcp_app/views/widgets" }), react()],
  resolve: {
    alias: {
      "@widgets": widgetsDir,
      "@": viewsDir,
    },
  },
});
