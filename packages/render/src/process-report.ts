interface DenoBuildInfo {
  os: string;
  env?: string;
}

function isLinuxGnuBuild(): boolean {
  const deno = (globalThis as typeof globalThis & { Deno?: { build: DenoBuildInfo } }).Deno;
  return deno?.build.os === "linux" && deno.build.env === "gnu";
}

// Mirror Deno process.report libc signaling without hostname/networkInterfaces sys grants.
export function sanitizedProcessReport(): { header: Record<string, string>; sharedObjects: undefined } {
  const header: Record<string, string> = isLinuxGnuBuild()
    ? { glibcVersionRuntime: "2.38", glibcVersionCompiler: "2.38" }
    : {};
  return { header, sharedObjects: undefined };
}

// Install before vite/rolldown load so requireNative's libc probe does not need networkInterfaces.
process.report.getReport = sanitizedProcessReport;
