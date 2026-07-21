import path from "node:path";

import { belgie } from "@belgie/mcp/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

const viewsDir = path.resolve(import.meta.dirname, "src/mcp_app/views");
const widgetsDir = path.resolve(viewsDir, "widgets");

export default defineConfig({
  plugins: [belgie({ srcDir: "src/mcp_app/views/widgets" }), react()],
  resolve: {
    alias: {
      "@": viewsDir,
      "@widgets": widgetsDir,
    },
  },
});
