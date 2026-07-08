use std::path::{Path, PathBuf};
use std::process::Command;
use std::{env, fs, io::Write};

const NAPI_EXPORTS_DEF: &str = "napi/generated_symbol_exports_list_windows.def";
const CORE_FORWARDER_TARGET: &str = "_core";

fn main() {
    let target_os = env::var("CARGO_CFG_TARGET_OS").unwrap_or_default();
    if target_os != "windows" {
        return;
    }
    if env::var("CARGO_FEATURE_EXTENSION_MODULE").is_err() {
        return;
    }
    let target_env = env::var("CARGO_CFG_TARGET_ENV").unwrap_or_default();
    if target_env != "msvc" {
        println!(
            "cargo:warning=Belgie Windows native addon host requires the MSVC toolchain (found {target_env})"
        );
        return;
    }

    let manifest_dir = PathBuf::from(env::var("CARGO_MANIFEST_DIR").expect("CARGO_MANIFEST_DIR"));
    let out_dir = PathBuf::from(env::var("OUT_DIR").expect("OUT_DIR"));
    let exports_def = manifest_dir.join(NAPI_EXPORTS_DEF);
    println!("cargo:rerun-if-changed={}", exports_def.display());

    let symbols = read_export_symbols(&exports_def).unwrap_or_else(|error| {
        panic!("Failed to read {}: {error}", exports_def.display());
    });

    let core_def = out_dir.join("_core_napi_exports.def");
    write_core_exports_def(&core_def, &symbols).unwrap_or_else(|error| {
        panic!("Failed to write {}: {error}", core_def.display());
    });
    println!("cargo:rustc-link-arg-cdylib=/DEF:{}", core_def.display());

    let libnode_def = out_dir.join("libnode.def");
    write_libnode_forwarder_def(&libnode_def, &symbols).unwrap_or_else(|error| {
        panic!("Failed to write {}: {error}", libnode_def.display());
    });
    let libnode_dll = out_dir.join("libnode.dll");
    link_libnode_forwarder(&libnode_def, &libnode_dll).unwrap_or_else(|error| {
        panic!("Failed to link {}: {error}", libnode_dll.display());
    });
    println!("cargo:rerun-if-changed=build.rs");
}

fn read_export_symbols(path: &Path) -> Result<Vec<String>, String> {
    let text = fs::read_to_string(path).map_err(|error| error.to_string())?;
    let mut symbols = Vec::new();
    let mut in_exports = false;
    for line in text.lines() {
        let trimmed = line.trim();
        if trimmed.eq_ignore_ascii_case("EXPORTS") {
            in_exports = true;
            continue;
        }
        if !in_exports || trimmed.is_empty() {
            continue;
        }
        if trimmed.starts_with(';') {
            continue;
        }
        let symbol = trimmed.split_whitespace().next().unwrap_or(trimmed);
        symbols.push(symbol.to_string());
    }
    if symbols.is_empty() {
        return Err(format!("No export symbols found in {}", path.display()));
    }
    Ok(symbols)
}

fn write_core_exports_def(path: &Path, symbols: &[String]) -> Result<(), String> {
    let mut file = fs::File::create(path).map_err(|error| error.to_string())?;
    writeln!(file, "LIBRARY").map_err(|error| error.to_string())?;
    writeln!(file, "EXPORTS").map_err(|error| error.to_string())?;
    writeln!(file, "  PyInit__core").map_err(|error| error.to_string())?;
    for symbol in symbols {
        writeln!(file, "  {symbol}").map_err(|error| error.to_string())?;
    }
    Ok(())
}

fn write_libnode_forwarder_def(path: &Path, symbols: &[String]) -> Result<(), String> {
    let mut file = fs::File::create(path).map_err(|error| error.to_string())?;
    writeln!(file, "LIBRARY libnode").map_err(|error| error.to_string())?;
    writeln!(file, "EXPORTS").map_err(|error| error.to_string())?;
    for symbol in symbols {
        writeln!(file, "  {symbol} = {CORE_FORWARDER_TARGET}.{symbol}")
            .map_err(|error| error.to_string())?;
    }
    Ok(())
}

fn link_libnode_forwarder(def_path: &Path, output_path: &Path) -> Result<(), String> {
    let linker = find_msvc_link_exe()?;
    let status = Command::new(&linker)
        .arg("/NOENTRY")
        .arg("/DLL")
        .arg(format!("/DEF:{}", def_path.display()))
        .arg(format!("/OUT:{}", output_path.display()))
        .status()
        .map_err(|error| format!("running {} failed: {error}", linker.display()))?;
    if !status.success() {
        return Err(format!(
            "{} failed while building {}",
            linker.display(),
            output_path.display()
        ));
    }
    Ok(())
}

fn find_msvc_link_exe() -> Result<PathBuf, String> {
    let host = env::var("HOST").unwrap_or_default();
    let target = env::var("TARGET").unwrap_or_default();

    if let Some(linker) = find_link_exe_via_cc(&host, &target) {
        return Ok(linker);
    }

    for candidate in msvc_link_candidates_from_vc_env(&host, &target) {
        if candidate.is_file() {
            return Ok(candidate);
        }
    }

    if let Ok(path) = env::var("PATH") {
        for dir in env::split_paths(&path) {
            let candidate = dir.join("link.exe");
            if candidate.is_file() && is_msvc_link_exe(&candidate) {
                return Ok(candidate);
            }
        }
    }

    Err(format!(
        "Could not find MSVC link.exe (host={host}, target={target})"
    ))
}

fn find_link_exe_via_cc(host: &str, target: &str) -> Option<PathBuf> {
    let mut cc_builder = cc::Build::new();
    cc_builder.target(target);
    cc_builder.host(host);
    let compiler = cc_builder.get_compiler();
    let compiler_path = PathBuf::from(compiler.path());
    let tool_root = compiler_path.parent()?;
    let linker = tool_root.join(if compiler.is_like_msvc() {
        "link.exe"
    } else {
        "lld-link.exe"
    });
    linker.is_file().then_some(linker)
}

fn msvc_link_candidates_from_vc_env(host: &str, target: &str) -> Vec<PathBuf> {
    let host_arch = msvc_arch_name(host);
    let target_arch = msvc_arch_name(target);
    let relative_bins = [
        PathBuf::from(format!("bin/Host{host_arch}/{target_arch}/link.exe")),
        PathBuf::from(format!("bin/Host{host_arch}/{host_arch}/link.exe")),
        PathBuf::from("bin/Hostx64/x64/link.exe"),
        PathBuf::from("bin/Hostx86/x86/link.exe"),
    ];

    let mut candidates = Vec::new();
    for key in ["VCToolsInstallDir", "VCINSTALLDIR"] {
        let Ok(root) = env::var(key) else {
            continue;
        };
        let root = PathBuf::from(root);
        for relative in &relative_bins {
            candidates.push(root.join(relative));
        }
        // VCINSTALLDIR points at the VC root; tools live under Tools\MSVC\<ver>\.
        if key == "VCINSTALLDIR" {
            let tools_msvc = root.join("Tools").join("MSVC");
            if let Ok(entries) = fs::read_dir(&tools_msvc) {
                for entry in entries.flatten() {
                    let version_root = entry.path();
                    for relative in &relative_bins {
                        candidates.push(version_root.join(relative));
                    }
                }
            }
        }
    }
    candidates
}

fn msvc_arch_name(triple: &str) -> &'static str {
    match triple.split('-').next().unwrap_or(triple) {
        "aarch64" | "arm64" => "arm64",
        "i686" | "i586" | "x86" => "x86",
        _ => "x64",
    }
}

fn is_msvc_link_exe(path: &Path) -> bool {
    let normalized = path
        .to_string_lossy()
        .replace('/', "\\")
        .to_ascii_lowercase();
    // Git for Windows ships GNU coreutils link.exe on PATH; reject it and similar traps.
    if normalized.contains("\\git\\usr\\bin\\") || normalized.contains("\\git\\bin\\") {
        return false;
    }
    if normalized.contains("\\vc\\tools\\msvc\\") {
        return true;
    }
    // Accept PATH entries that sit next to cl.exe (typical developer command prompt layout).
    path.parent()
        .map(|dir| dir.join("cl.exe").is_file())
        .unwrap_or(false)
}
