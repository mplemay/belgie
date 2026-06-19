use tokio::sync::{Mutex, MutexGuard, watch};

use crate::types::error::BindingError;

static PROCESS_CONTEXT_LOCK: Mutex<()> = Mutex::const_new(());

pub(crate) fn blocking_guard() -> MutexGuard<'static, ()> {
    PROCESS_CONTEXT_LOCK.blocking_lock()
}

pub(crate) fn command_cancelled() -> BindingError {
    BindingError::runtime("Command was cancelled")
}

pub(crate) fn watch_cancelled(
    changed: Result<(), watch::error::RecvError>,
    cancel_rx: &watch::Receiver<bool>,
) -> bool {
    changed.is_err() || *cancel_rx.borrow()
}

pub(crate) async fn acquire_guard(
    cancel_rx: &mut watch::Receiver<bool>,
) -> Result<MutexGuard<'static, ()>, BindingError> {
    if *cancel_rx.borrow() {
        return Err(command_cancelled());
    }
    let guard = loop {
        tokio::select! {
            guard = PROCESS_CONTEXT_LOCK.lock() => break guard,
            changed = cancel_rx.changed() => {
                if watch_cancelled(changed, cancel_rx) {
                    return Err(command_cancelled());
                }
            }
        }
    };
    if *cancel_rx.borrow() {
        return Err(command_cancelled());
    }
    Ok(guard)
}
