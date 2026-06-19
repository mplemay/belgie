use std::sync::{Mutex, TryLockError};
use std::time::Duration;

use tokio::sync::watch;

use crate::types::error::BindingError;

const ACQUIRE_RETRY_DELAY: Duration = Duration::from_millis(5);

static PROCESS_CONTEXT_LOCK: Mutex<bool> = Mutex::new(false);

#[derive(Debug)]
pub(crate) struct ProcessContextGuard;

pub(crate) fn blocking_guard() -> ProcessContextGuard {
    loop {
        if let Some(guard) = try_acquire_guard() {
            return guard;
        }
        std::thread::sleep(ACQUIRE_RETRY_DELAY);
    }
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
) -> Result<ProcessContextGuard, BindingError> {
    if *cancel_rx.borrow() {
        return Err(command_cancelled());
    }
    loop {
        if let Some(guard) = try_acquire_guard() {
            if *cancel_rx.borrow() {
                drop(guard);
                return Err(command_cancelled());
            }
            return Ok(guard);
        }
        tokio::select! {
            changed = cancel_rx.changed() => {
                if watch_cancelled(changed, cancel_rx) {
                    return Err(command_cancelled());
                }
            }
            () = tokio::time::sleep(ACQUIRE_RETRY_DELAY) => {}
        }
    }
}

fn try_acquire_guard() -> Option<ProcessContextGuard> {
    let mut active = match PROCESS_CONTEXT_LOCK.try_lock() {
        Ok(active) => active,
        Err(TryLockError::WouldBlock) => return None,
        Err(TryLockError::Poisoned(error)) => {
            panic!("process context lock should not be poisoned: {error}");
        }
    };
    if *active {
        return None;
    }
    *active = true;
    Some(ProcessContextGuard)
}

impl Drop for ProcessContextGuard {
    fn drop(&mut self) {
        *PROCESS_CONTEXT_LOCK
            .lock()
            .expect("process context lock should not be poisoned") = false;
    }
}

#[cfg(test)]
mod tests {
    use super::{acquire_guard, blocking_guard, command_cancelled, try_acquire_guard};
    use std::time::Duration;
    use tokio::sync::watch;

    fn run_async(test: impl Future<Output = ()>) {
        tokio::runtime::Builder::new_current_thread()
            .enable_time()
            .build()
            .expect("test runtime should build")
            .block_on(test);
    }

    #[test]
    fn blocking_guard_excludes_other_callers() {
        let guard = blocking_guard();
        assert!(try_acquire_guard().is_none());

        drop(guard);

        let next = try_acquire_guard().expect("guard should be available after release");
        drop(next);
    }

    #[test]
    fn async_guard_waits_for_blocking_guard_to_release() {
        run_async(async {
            let guard = blocking_guard();
            let (_cancel_tx, mut cancel_rx) = watch::channel(false);

            let timed_out =
                tokio::time::timeout(Duration::from_millis(20), acquire_guard(&mut cancel_rx))
                    .await
                    .is_err();
            assert!(timed_out);

            drop(guard);

            let next =
                tokio::time::timeout(Duration::from_millis(50), acquire_guard(&mut cancel_rx))
                    .await
                    .expect("guard acquisition should finish")
                    .expect("guard should acquire after release");
            drop(next);
        });
    }

    #[test]
    fn async_guard_waiting_for_context_is_cancellable() {
        run_async(async {
            let guard = blocking_guard();
            let (cancel_tx, mut cancel_rx) = watch::channel(false);
            let mut waiting = Box::pin(acquire_guard(&mut cancel_rx));

            let timed_out = tokio::time::timeout(Duration::from_millis(20), &mut waiting)
                .await
                .is_err();
            assert!(timed_out);

            cancel_tx
                .send(true)
                .expect("cancel signal should be delivered");
            let error = waiting
                .await
                .expect_err("waiting guard should be cancelled");
            assert_eq!(error.message(), command_cancelled().message());

            drop(guard);

            let (_cancel_tx, mut cancel_rx) = watch::channel(false);
            let next =
                tokio::time::timeout(Duration::from_millis(50), acquire_guard(&mut cancel_rx))
                    .await
                    .expect("guard acquisition should finish after cancellation")
                    .expect("guard should acquire after cancellation");
            drop(next);
        });
    }
}
