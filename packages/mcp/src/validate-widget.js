function stripComments(code) {
  return code.replace(/\/\/.*$/gm, "").replace(/\/\*[\s\S]*?\*\//g, "");
}

export function hasDefaultExport(code) {
  const stripped = stripComments(code);
  return (
    /export\s+default\s/.test(stripped) ||
    /export\s*\{[^}]*\bas\s+default\b[^}]*}/.test(stripped)
  );
}
