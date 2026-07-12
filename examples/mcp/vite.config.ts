import { belgie } from "@belgie/mcp/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [belgie(), react()],
});
