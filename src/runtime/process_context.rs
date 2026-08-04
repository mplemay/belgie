use std::sync::{Mutex, TryLockError};
use std::time::Duration;

use tokio::sync::watch;

use crate::types::error::BindingError;

const ACQUIRE_RETRY_DELAY: Duration = Duration::from_millis(5);

static PROCESS_CONTEXT_LOCK: ProcessContextLock = ProcessContextLock::new();

#[derive(Debug)]
struct ProcessContextLock {
    active: Mutex<bool>,
}

#[derive(Debug)]
pub(crate) struct ProcessContextGuard<'lock> {
    lock: &'lock ProcessContextLock,
}

impl ProcessContextLock {
    const fn new() -> Self {
        Self {
            active: Mutex::new(false),
        }
    }

    fn blocking_guard(&self) -> ProcessContextGuard<'_> {
        loop {
            if let Some(guard) = self.try_acquire_guard() {
                return guard;
            }
            std::thread::sleep(ACQUIRE_RETRY_DELAY);
        }
    }

    async fn acquire_guard(
        &self,
        cancel_rx: &mut watch::Receiver<bool>,
    ) -> Result<ProcessContextGuard<'_>, BindingError> {
        if *cancel_rx.borrow() {
            return Err(command_cancelled());
        }
        loop {
            if let Some(guard) = self.try_acquire_guard() {
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

    fn try_acquire_guard(&self) -> Option<ProcessContextGuard<'_>> {
        let mut active = match self.active.try_lock() {
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
        Some(ProcessContextGuard { lock: self })
    }
}

pub(crate) fn blocking_guard() -> ProcessContextGuard<'static> {
    PROCESS_CONTEXT_LOCK.blocking_guard()
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
) -> Result<ProcessContextGuard<'static>, BindingError> {
    PROCESS_CONTEXT_LOCK.acquire_guard(cancel_rx).await
}

impl Drop for ProcessContextGuard<'_> {
    fn drop(&mut self) {
        *self
            .lock
            .active
            .lock()
            .expect("process context lock should not be poisoned") = false;
    }
}

#[cfg(test)]
mod tests {
    use super::{ProcessContextLock, command_cancelled};
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
        let context_lock = ProcessContextLock::new();
        let guard = context_lock.blocking_guard();
        assert!(context_lock.try_acquire_guard().is_none());

        drop(guard);

        let next = context_lock
            .try_acquire_guard()
            .expect("guard should be available after release");
        drop(next);
    }

    #[test]
    fn async_guard_waits_for_blocking_guard_to_release() {
        run_async(async {
            let context_lock = ProcessContextLock::new();
            let guard = context_lock.blocking_guard();
            let (_cancel_tx, mut cancel_rx) = watch::channel(false);

            let timed_out = tokio::time::timeout(
                Duration::from_millis(20),
                context_lock.acquire_guard(&mut cancel_rx),
            )
            .await
            .is_err();
            assert!(timed_out);

            drop(guard);

            let next = tokio::time::timeout(
                Duration::from_millis(50),
                context_lock.acquire_guard(&mut cancel_rx),
            )
            .await
            .expect("guard acquisition should finish")
            .expect("guard should acquire after release");
            drop(next);
        });
    }

    #[test]
    fn async_guard_waiting_for_context_is_cancellable() {
        run_async(async {
            let context_lock = ProcessContextLock::new();
            let guard = context_lock.blocking_guard();
            let (cancel_tx, mut cancel_rx) = watch::channel(false);
            let mut waiting = Box::pin(context_lock.acquire_guard(&mut cancel_rx));

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
            let next = tokio::time::timeout(
                Duration::from_millis(50),
                context_lock.acquire_guard(&mut cancel_rx),
            )
            .await
            .expect("guard acquisition should finish after cancellation")
            .expect("guard should acquire after cancellation");
            drop(next);
        });
    }
}
