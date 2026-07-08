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

#[cfg(all(windows, feature = "extension-module"))]
mod imp {
    use std::ffi::OsString;
    use std::os::windows::ffi::{OsStrExt, OsStringExt};
    use std::path::{Path, PathBuf};
    use std::sync::OnceLock;

    use windows_sys::Win32::Foundation::HMODULE;
    use windows_sys::Win32::System::LibraryLoader::{
        GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS, GET_MODULE_HANDLE_EX_FLAG_UNCHANGED_REFCOUNT,
        GetModuleFileNameW, GetModuleHandleExW, GetProcAddress, LoadLibraryW,
    };

    use crate::types::error::BindingError;

    const LIBNODE_DLL: &str = "libnode.dll";
    const NAPI_PROBE_SYMBOL: &[u8] = b"napi_create_int32\0";

    static LOAD_RESULT: OnceLock<Result<(), String>> = OnceLock::new();

    pub(crate) fn ensure_symbols_visible() -> Result<(), BindingError> {
        match LOAD_RESULT.get_or_init(load_libnode_forwarder) {
            Ok(()) => Ok(()),
            Err(message) => Err(BindingError::runtime(message.clone())),
        }
    }

    fn load_libnode_forwarder() -> Result<(), String> {
        let core_path = current_library_path()?;
        let libnode_path = core_path
            .parent()
            .ok_or_else(|| {
                format!(
                    "Could not resolve parent directory for Belgie runtime at {}",
                    core_path.display()
                )
            })?
            .join(LIBNODE_DLL);
        if !libnode_path.is_file() {
            return Err(format!(
                "Missing {LIBNODE_DLL} next to Belgie runtime at {}",
                core_path.display()
            ));
        }
        let handle = load_library(&libnode_path)?;
        probe_napi_symbol(handle, &libnode_path)?;
        Ok(())
    }

    fn current_library_path() -> Result<PathBuf, String> {
        let mut handle = 0;
        let symbol = load_libnode_forwarder as *const () as *const std::ffi::c_void;
        // SAFETY: symbol is a function in the loaded extension and out handle is valid.
        let found = unsafe {
            GetModuleHandleExW(
                GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS
                    | GET_MODULE_HANDLE_EX_FLAG_UNCHANGED_REFCOUNT,
                symbol,
                &mut handle,
            )
        };
        if found == 0 || handle == 0 {
            return Err(
                "Could not locate the loaded Belgie runtime library on Windows".to_string(),
            );
        }
        module_path(handle)
    }

    fn module_path(handle: HMODULE) -> Result<PathBuf, String> {
        let mut buffer = vec![0u16; 32_768];
        // SAFETY: handle came from GetModuleHandleExW and buffer is valid.
        let length =
            unsafe { GetModuleFileNameW(handle, buffer.as_mut_ptr(), buffer.len() as u32) };
        if length == 0 || length as usize >= buffer.len() {
            return Err("Could not resolve Belgie runtime path on Windows".to_string());
        }
        buffer.truncate(length as usize);
        Ok(PathBuf::from(OsString::from_wide(&buffer)))
    }

    fn load_library(path: &Path) -> Result<HMODULE, String> {
        let wide = wide_path(path)?;
        // SAFETY: wide path is null-terminated UTF-16 for LoadLibraryW.
        let handle = unsafe { LoadLibraryW(wide.as_ptr()) };
        if handle == 0 {
            return Err(format!(
                "Could not load {} for native npm addons",
                path.display()
            ));
        }
        Ok(handle)
    }

    fn probe_napi_symbol(handle: HMODULE, path: &Path) -> Result<(), String> {
        // SAFETY: handle is a loaded module and the symbol name is static.
        let symbol = unsafe { GetProcAddress(handle, NAPI_PROBE_SYMBOL.as_ptr()) };
        if symbol == 0 {
            return Err(format!(
                "Loaded {} but could not resolve Node-API exports",
                path.display()
            ));
        }
        Ok(())
    }

    fn wide_path(path: &Path) -> Result<Vec<u16>, String> {
        let mut wide: Vec<u16> = path.as_os_str().encode_wide().chain([0]).collect();
        if wide.len() == 1 {
            return Err(format!("Invalid library path {}", path.display()));
        }
        Ok(wide)
    }

    use std::ffi::OsString;
}

#[cfg(not(any(
    all(unix, feature = "extension-module"),
    all(windows, feature = "extension-module")
)))]
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
