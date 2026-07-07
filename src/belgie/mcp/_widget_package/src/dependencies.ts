export const BUILD_DEPENDENCIES = {
  "@modelcontextprotocol/ext-apps": "npm:@modelcontextprotocol/ext-apps@latest",
  "@modelcontextprotocol/sdk": "npm:@modelcontextprotocol/sdk@latest",
  "@vitejs/plugin-react": "npm:@vitejs/plugin-react@^4",
  react: "npm:react@^19",
  "react-dom": "npm:react-dom@^19",
  vite: "npm:vite@6.1.0",
  "vite-plugin-singlefile": "npm:vite-plugin-singlefile@^2",
};

export default function dependencies(): Record<string, string> {
  return { ...BUILD_DEPENDENCIES };
}
