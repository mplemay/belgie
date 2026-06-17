use deno_core::anyhow::anyhow;
use deno_core::error::AnyError;

pub(crate) fn run_outside_runtime<F, T>(operation: F) -> Result<T, AnyError>
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
