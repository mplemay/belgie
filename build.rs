use std::path::PathBuf;

fn main() {
    let target_os = std::env::var("CARGO_CFG_TARGET_OS").unwrap_or_default();
    if target_os != "windows" {
        return;
    }

    let manifest_dir = PathBuf::from(
        std::env::var_os("CARGO_MANIFEST_DIR").expect("CARGO_MANIFEST_DIR should be set"),
    );
    let exports = manifest_dir
        .join("build")
        .join("napi")
        .join("generated_symbol_exports_list_windows.def");

    println!("cargo:rerun-if-changed={}", exports.display());
    println!("cargo:rustc-link-arg-cdylib=/DEF:{}", exports.display());
}
