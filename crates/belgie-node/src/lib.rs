use std::path::PathBuf;
use std::sync::atomic::{AtomicBool, AtomicU32, Ordering};
use std::sync::{Arc, Weak};
use std::time::Duration;

use belgie_pool::{Pool, PoolError, PoolOptions, RunnerLease};
use napi::bindgen_prelude::*;
use napi_derive::napi;
use tokio::sync::Mutex;

const ERROR_PREFIX: &str = "BELGIE_ERROR:";

#[napi(object)]
pub struct NativeRuntimeOptions {
    pub worker_path: String,
    pub min_workers: u32,
    pub max_workers: u32,
    pub checkout_timeout_ms: u32,
    pub run_timeout_ms: u32,
    pub max_old_generation_size_mb: u32,
}

#[napi]
pub struct NativeRuntime {
    pool: Arc<Pool>,
    runners: Arc<Mutex<Vec<Weak<NativeRunnerInner>>>>,
    closed: AtomicBool,
}

#[napi]
impl NativeRuntime {
    #[napi(factory)]
    pub async fn create(options: NativeRuntimeOptions) -> Result<Self> {
        let mut pool_options = PoolOptions::new(PathBuf::from(options.worker_path));
        pool_options.min_workers = options.min_workers as usize;
        pool_options.max_workers = options.max_workers as usize;
        pool_options.checkout_timeout = Duration::from_millis(options.checkout_timeout_ms.into());
        pool_options.run_timeout = Duration::from_millis(options.run_timeout_ms.into());
        pool_options.max_old_generation_size_mb = options.max_old_generation_size_mb.into();
        let pool = Pool::create(pool_options).await.map_err(to_napi_error)?;
        Ok(Self {
            pool,
            runners: Arc::new(Mutex::new(Vec::new())),
            closed: AtomicBool::new(false),
        })
    }

    #[napi]
    pub async fn bind(&self, source: String) -> Result<NativeRunner> {
        if self.closed.load(Ordering::Acquire) {
            return Err(to_napi_error(PoolError::Closed));
        }
        let lease = self.pool.bind(source).await.map_err(to_napi_error)?;
        let inner = Arc::new(NativeRunnerInner {
            lease: Mutex::new(Some(lease)),
            closed: AtomicBool::new(false),
            running: AtomicBool::new(false),
            process_id: AtomicU32::new(0),
        });
        if let Some(process_id) = inner
            .lease
            .lock()
            .await
            .as_ref()
            .and_then(RunnerLease::process_id)
        {
            inner.process_id.store(process_id, Ordering::Release);
        }
        let mut runners = self.runners.lock().await;
        runners.retain(|runner| runner.strong_count() > 0);
        runners.push(Arc::downgrade(&inner));
        Ok(NativeRunner { inner })
    }

    #[napi]
    pub async fn close(&self) -> Result<()> {
        if self.closed.swap(true, Ordering::AcqRel) {
            return Ok(());
        }
        let runners = {
            let mut runners = self.runners.lock().await;
            std::mem::take(&mut *runners)
        };
        for runner in runners.into_iter().filter_map(|runner| runner.upgrade()) {
            runner.discard().await;
        }
        self.pool.close().await;
        Ok(())
    }
}

#[napi]
pub struct NativeRunner {
    inner: Arc<NativeRunnerInner>,
}

#[napi]
impl NativeRunner {
    #[napi]
    pub async fn run(&self, arguments_json: String) -> Result<String> {
        if self.inner.closed.load(Ordering::Acquire) {
            return Err(to_napi_error(PoolError::Closed));
        }
        let arguments = serde_json::from_str(&arguments_json).map_err(|error| {
            to_napi_error(PoolError::Protocol(format!(
                "Arguments are not valid JSON: {error}",
            )))
        })?;
        let serde_json::Value::Array(arguments) = arguments else {
            return Err(to_napi_error(PoolError::Protocol(
                "Arguments payload must be a JSON array".to_string(),
            )));
        };
        self.inner.running.store(true, Ordering::Release);
        if self.inner.closed.load(Ordering::Acquire) {
            self.inner.running.store(false, Ordering::Release);
            return Err(to_napi_error(PoolError::Closed));
        }
        let mut lease = self.inner.lease.lock().await;
        let Some(lease) = lease.as_mut() else {
            self.inner.running.store(false, Ordering::Release);
            return Err(to_napi_error(PoolError::Closed));
        };
        let value = lease.run(arguments).await;
        self.inner
            .process_id
            .store(lease.process_id().unwrap_or_default(), Ordering::Release);
        self.inner.running.store(false, Ordering::Release);
        let value = value.map_err(to_napi_error)?;
        serde_json::to_string(&value).map_err(|error| {
            to_napi_error(PoolError::Protocol(format!(
                "Result could not be encoded as JSON: {error}",
            )))
        })
    }

    #[napi]
    pub async fn close(&self) -> Result<()> {
        self.inner.close().await;
        Ok(())
    }
}

struct NativeRunnerInner {
    lease: Mutex<Option<RunnerLease>>,
    closed: AtomicBool,
    running: AtomicBool,
    process_id: AtomicU32,
}

impl NativeRunnerInner {
    async fn close(&self) {
        if self.closed.swap(true, Ordering::AcqRel) {
            return;
        }
        let was_running = self.running.load(Ordering::Acquire);
        if was_running {
            self.terminate_worker();
        }
        if let Some(mut lease) = self.lease.lock().await.take() {
            if was_running {
                lease.discard().await;
            } else {
                lease.close().await;
            }
        }
        self.process_id.store(0, Ordering::Release);
    }

    async fn discard(&self) {
        self.closed.store(true, Ordering::Release);
        self.terminate_worker();
        if let Some(mut lease) = self.lease.lock().await.take() {
            lease.discard().await;
        }
        self.process_id.store(0, Ordering::Release);
    }

    fn terminate_worker(&self) {
        let process_id = self.process_id.load(Ordering::Acquire);
        if process_id == 0 {
            return;
        }
        #[cfg(unix)]
        unsafe {
            libc::kill(process_id as libc::pid_t, libc::SIGKILL);
        }
    }
}

impl Drop for NativeRunner {
    fn drop(&mut self) {
        if Arc::strong_count(&self.inner) != 1 || self.inner.closed.load(Ordering::Acquire) {
            return;
        }
        if let Ok(handle) = napi::tokio::runtime::Handle::try_current() {
            let inner = self.inner.clone();
            handle.spawn(async move {
                inner.discard().await;
            });
        } else {
            self.inner.closed.store(true, Ordering::Release);
            self.inner.terminate_worker();
        }
    }
}

fn to_napi_error(error: PoolError) -> Error {
    let payload = serde_json::json!({
        "kind": error.kind(),
        "code": error.code(),
        "message": error.to_string(),
    });
    Error::new(Status::GenericFailure, format!("{ERROR_PREFIX}{payload}"))
}
