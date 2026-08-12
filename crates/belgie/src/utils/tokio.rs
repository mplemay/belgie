use std::sync::OnceLock;

use deno_core::anyhow::anyhow;
use deno_core::error::AnyError;
use tokio::runtime::Runtime;

static RUNTIME: OnceLock<Runtime> = OnceLock::new();

fn runtime() -> &'static Runtime {
    RUNTIME.get_or_init(|| {
        tokio::runtime::Builder::new_multi_thread()
            .enable_all()
            .build()
            .expect("failed to create belgie tokio runtime")
    })
}

pub fn run_outside_runtime<F, T>(operation: F) -> Result<T, AnyError>
where
    F: FnOnce() -> Result<T, AnyError> + Send,
    T: Send,
{
    if tokio::runtime::Handle::try_current().is_ok() {
        std::thread::scope(|scope| {
            scope
                .spawn(operation)
                .join()
                .map_err(|_| anyhow!("Belgie sync thread panicked"))?
        })
    } else {
        operation()
    }
}

pub fn block_on_outside_runtime<F, Fut, T>(make_future: F) -> Result<T, AnyError>
where
    F: FnOnce() -> Fut + Send,
    Fut: std::future::Future<Output = Result<T, AnyError>>,
    T: Send,
{
    run_outside_runtime(|| runtime().block_on(make_future()))
}
