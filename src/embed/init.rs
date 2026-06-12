use std::sync::Once;

use deno_core::JsRuntime;
use deno_lib::args::get_root_cert_store;

static INIT: Once = Once::new();

pub(crate) fn ensure_initialized() {
    INIT.call_once(|| {
        deno_lib::util::logger::init(deno_lib::util::logger::InitLoggingOptions {
            maybe_level: None,
            otel_config: None,
            on_log_start: || {},
            on_log_end: || {},
        });
        rustls::crypto::aws_lc_rs::default_provider()
            .install_default()
            .expect("failed to install rustls crypto provider");
        JsRuntime::init_platform(None);
        // Warm root cert store so HTTPS fetches work.
        let _ = get_root_cert_store(&EmbedSys::default(), None, None, None);
    });
}

use crate::embed::sys::EmbedSys;
