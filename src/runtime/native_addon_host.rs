#[cfg(unix)]
mod imp {
    use std::ffi::CStr;
    use std::mem::MaybeUninit;
    use std::os::raw::c_void;
    use std::sync::OnceLock;

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
        // SAFETY: the path came from dladdr and identifies the already-loaded extension.
        unsafe {
            libc::dlerror();
            let handle = libc::dlopen(
                info.dli_fname,
                libc::RTLD_LAZY | libc::RTLD_NOLOAD | libc::RTLD_GLOBAL,
            );
            if handle.is_null() {
                let path = CStr::from_ptr(info.dli_fname).to_string_lossy();
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

#[cfg(not(unix))]
mod imp {
    use crate::types::error::BindingError;

    pub(crate) fn ensure_symbols_visible() -> Result<(), BindingError> {
        Ok(())
    }
}

pub(crate) use imp::ensure_symbols_visible;
