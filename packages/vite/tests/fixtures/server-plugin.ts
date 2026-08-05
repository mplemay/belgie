export function makePlugin() {
  return {
    name: "fixture-plugin",
    renderChunk(code: string) {
      return code.replace("fixture-target", "fixture-applied");
    },
  };
}
