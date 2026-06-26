#[cfg(any(test, all(unix, feature = "extension-module")))]
fn is_promotable_shared_library_path(path: &std::path::Path) -> bool {
    matches!(
        path.extension().and_then(|extension| extension.to_str()),
        Some("so" | "dylib" | "bundle")
    )
}

#[cfg(all(unix, feature = "extension-module"))]
mod imp {
    use std::ffi::CStr;
    use std::mem::MaybeUninit;
    use std::os::raw::c_void;
    use std::path::Path;
    use std::sync::OnceLock;

    use super::is_promotable_shared_library_path;
    use crate::types::error::BindingError;

    static PROMOTION_RESULT: OnceLock<Result<(), String>> = OnceLock::new();

    pub(crate) fn ensure_symbols_visible() -> Result<(), BindingError> {
        match PROMOTION_RESULT.get_or_init(promote_current_library) {
            Ok(()) => Ok(()),
            Err(message) => Err(BindingError::runtime(message.clone())),
        }
    }

    fn promote_current_library() -> Result<(), String> {
        let mut info = MaybeUninit::<libc::Dl_info>::zeroed();
        let symbol = promote_current_library as *const () as *const c_void;
        // SAFETY: dladdr receives a valid function address and output pointer.
        if unsafe { libc::dladdr(symbol, info.as_mut_ptr()) } == 0 {
            return Err(dlerror_or(
                "Could not locate the loaded Belgie runtime library",
            ));
        }
        // SAFETY: dladdr initialized info after returning non-zero.
        let info = unsafe { info.assume_init() };
        if info.dli_fname.is_null() {
            return Err("Could not locate the loaded Belgie runtime library path".to_string());
        }
        let path = unsafe { CStr::from_ptr(info.dli_fname) }
            .to_string_lossy()
            .into_owned();
        if !is_promotable_shared_library_path(Path::new(&path)) {
            return Ok(());
        }
        // SAFETY: the path came from dladdr and identifies the already-loaded extension.
        unsafe {
            libc::dlerror();
            let handle = libc::dlopen(
                info.dli_fname,
                libc::RTLD_LAZY | libc::RTLD_NOLOAD | libc::RTLD_GLOBAL,
            );
            if handle.is_null() {
                return Err(format!(
                    "Could not make Belgie runtime symbols visible for native npm addons at {path}: {}",
                    dlerror_or("dlopen failed"),
                ));
            }
        }
        Ok(())
    }

    fn dlerror_or(default: &str) -> String {
        // SAFETY: dlerror returns either null or a valid C error string.
        let error = unsafe { libc::dlerror() };
        if error.is_null() {
            default.to_string()
        } else {
            // SAFETY: non-null dlerror pointers reference a null-terminated string.
            unsafe { CStr::from_ptr(error) }
                .to_string_lossy()
                .into_owned()
        }
    }
}

#[cfg(not(all(unix, feature = "extension-module")))]
mod imp {
    use crate::types::error::BindingError;

    pub(crate) fn ensure_symbols_visible() -> Result<(), BindingError> {
        Ok(())
    }
}

pub(crate) use imp::ensure_symbols_visible;

#[cfg(test)]
mod tests {
    use std::path::Path;

    use super::is_promotable_shared_library_path;

    #[test]
    fn promotes_linux_and_macos_shared_objects() {
        assert!(is_promotable_shared_library_path(Path::new(
            "/tmp/_core.cpython-312-x86_64-linux-gnu.so"
        )));
        assert!(is_promotable_shared_library_path(Path::new(
            "/tmp/_core.abi3.so"
        )));
        assert!(is_promotable_shared_library_path(Path::new(
            "/tmp/libbelgie_core.dylib"
        )));
        assert!(is_promotable_shared_library_path(Path::new(
            "/tmp/_core.bundle"
        )));
    }

    #[test]
    fn skips_cargo_test_executables_and_archives() {
        assert!(!is_promotable_shared_library_path(Path::new(
            "/tmp/native_addon_host-abc123"
        )));
        assert!(!is_promotable_shared_library_path(Path::new("/tmp/_core")));
        assert!(!is_promotable_shared_library_path(Path::new(
            "/tmp/libbelgie_core.rlib"
        )));
    }
}
