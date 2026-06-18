use std::path::Path;

fn main() {
    if std::env::var("CARGO_CFG_TARGET_OS").as_deref() == Ok("windows") {
        let manifest_dir =
            std::env::var("CARGO_MANIFEST_DIR").expect("CARGO_MANIFEST_DIR should be set");
        let symbols_path = Path::new(&manifest_dir)
            .join("napi_exports")
            .join("windows.def");
        println!("cargo:rerun-if-changed={}", symbols_path.display());
        println!(
            "cargo:rustc-link-arg-bin=belgie-task-runtime=/DEF:{}",
            symbols_path.display()
        );
    }
}
