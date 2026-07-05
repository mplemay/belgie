use std::sync::mpsc::{self, SyncSender};
use std::sync::{Once, OnceLock};
use std::thread::{self, JoinHandle};

use deno_core::JsRuntime;
use deno_lib::args::get_root_cert_store;

use crate::embed::sys::EmbedSys;

static GLOBAL_INIT: Once = Once::new();
static V8_HOST_TX: OnceLock<SyncSender<Box<dyn FnOnce() + Send>>> = OnceLock::new();

fn v8_host_sender() -> &'static SyncSender<Box<dyn FnOnce() + Send>> {
    V8_HOST_TX.get_or_init(|| {
        let (ready_tx, ready_rx) = mpsc::sync_channel::<()>(0);
        let (tx, rx) = mpsc::sync_channel::<Box<dyn FnOnce() + Send>>(0);
        thread::spawn(move || {
            JsRuntime::init_platform(None);
            let _ = ready_tx.send(());
            for job in rx {
                job();
            }
        });
        ready_rx
            .recv()
            .expect("v8 host thread should finish platform initialization");
        tx
    })
}

pub(crate) fn ensure_initialized() {
    GLOBAL_INIT.call_once(|| {
        deno_lib::util::logger::init(deno_lib::util::logger::InitLoggingOptions {
            maybe_level: None,
            otel_config: None,
            on_log_start: || {},
            on_log_end: || {},
        });
        rustls::crypto::aws_lc_rs::default_provider()
            .install_default()
            .expect("failed to install rustls crypto provider");
        let _ = get_root_cert_store(&EmbedSys::default(), None, None, None);
        let _ = v8_host_sender();
    });
}

pub(crate) fn spawn_v8_worker<F, T>(f: F) -> JoinHandle<T>
where
    F: FnOnce() -> T + Send + 'static,
    T: Send + 'static,
{
    ensure_initialized();
    let (done_tx, done_rx) = mpsc::sync_channel::<JoinHandle<T>>(0);
    v8_host_sender()
        .send(Box::new(move || {
            let handle = thread::spawn(f);
            let _ = done_tx.send(handle);
        }))
        .expect("v8 host thread should be alive");
    done_rx
        .recv()
        .expect("v8 host thread should return a join handle")
}
