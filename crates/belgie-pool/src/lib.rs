use std::collections::VecDeque;
use std::fmt::{Display, Formatter};
use std::path::PathBuf;
use std::process::Stdio;
use std::sync::{Arc, Mutex};
use std::time::Duration;

use belgie_protocol::{
    MAX_FRAME_SIZE, PROTOCOL_VERSION, Request, RequestCommand, Response, ResponseOutcome,
    ResponseResult, WorkerError, WorkerErrorKind, decode_payload, encode_frame,
};
use serde_json::Value;
use tempfile::TempDir;
use tokio::io::{AsyncReadExt, AsyncWriteExt, BufReader};
use tokio::process::{Child, ChildStderr, ChildStdin, ChildStdout, Command};
use tokio::sync::{Mutex as AsyncMutex, OwnedSemaphorePermit, Semaphore};
use tokio::task::JoinHandle;
use tokio::time::timeout;

const STDERR_TAIL_BYTES: usize = 16 * 1024;
const DEFAULT_RECYCLE_AFTER: u64 = 100;
const STARTUP_TIMEOUT: Duration = Duration::from_secs(10);

#[derive(Clone, Debug)]
pub struct PoolOptions {
    pub worker_path: PathBuf,
    pub min_workers: usize,
    pub max_workers: usize,
    pub checkout_timeout: Duration,
    pub run_timeout: Duration,
    pub max_old_generation_size_mb: u64,
    pub recycle_after: u64,
}

impl PoolOptions {
    pub fn new(worker_path: PathBuf) -> Self {
        Self {
            worker_path,
            min_workers: 1,
            max_workers: std::thread::available_parallelism()
                .map(usize::from)
                .unwrap_or(1),
            checkout_timeout: Duration::from_secs(30),
            run_timeout: Duration::from_secs(30),
            max_old_generation_size_mb: 128,
            recycle_after: DEFAULT_RECYCLE_AFTER,
        }
    }

    fn validate(&self) -> Result<(), PoolError> {
        if self.max_workers == 0 {
            return Err(PoolError::Configuration(
                "maxWorkers must be greater than zero".to_string(),
            ));
        }
        if self.min_workers > self.max_workers {
            return Err(PoolError::Configuration(
                "minWorkers must be less than or equal to maxWorkers".to_string(),
            ));
        }
        if self.max_old_generation_size_mb == 0 {
            return Err(PoolError::Configuration(
                "maxOldGenerationSizeMb must be greater than zero".to_string(),
            ));
        }
        if self.recycle_after == 0 {
            return Err(PoolError::Configuration(
                "recycleAfter must be greater than zero".to_string(),
            ));
        }
        Ok(())
    }
}

#[derive(Clone, Debug)]
pub enum PoolError {
    Configuration(String),
    Closed,
    CheckoutTimeout,
    RunTimeout,
    WorkerCrash { diagnostics: String },
    Protocol(String),
    Worker(WorkerError),
    Spawn(String),
}

impl PoolError {
    pub fn code(&self) -> &str {
        match self {
            Self::Configuration(_) => "invalid_options",
            Self::Closed => "runtime_closed",
            Self::CheckoutTimeout => "checkout_timeout",
            Self::RunTimeout => "run_timeout",
            Self::WorkerCrash { .. } => "worker_crash",
            Self::Protocol(_) => "protocol_failure",
            Self::Worker(error) => &error.code,
            Self::Spawn(_) => "worker_spawn",
        }
    }

    pub fn kind(&self) -> &str {
        match self {
            Self::Worker(error) => match error.kind {
                WorkerErrorKind::Module => "module",
                WorkerErrorKind::JavaScript => "javascript",
                WorkerErrorKind::Value => "value",
                WorkerErrorKind::Runtime | WorkerErrorKind::Protocol => "runtime",
            },
            _ => "runtime",
        }
    }

    fn poisons_worker(&self) -> bool {
        matches!(
            self,
            Self::RunTimeout
                | Self::WorkerCrash { .. }
                | Self::Protocol(_)
                | Self::Spawn(_)
                | Self::Worker(WorkerError {
                    kind: WorkerErrorKind::Protocol | WorkerErrorKind::Runtime,
                    ..
                })
        )
    }
}

impl Display for PoolError {
    fn fmt(&self, formatter: &mut Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::Configuration(message) | Self::Protocol(message) | Self::Spawn(message) => {
                formatter.write_str(message)
            }
            Self::Closed => formatter.write_str("Runtime is closed"),
            Self::CheckoutTimeout => formatter.write_str("Timed out waiting for a sandbox worker"),
            Self::RunTimeout => formatter.write_str("Sandbox execution timed out"),
            Self::WorkerCrash { diagnostics } if diagnostics.is_empty() => {
                formatter.write_str("Sandbox worker exited unexpectedly")
            }
            Self::WorkerCrash { diagnostics } => {
                write!(
                    formatter,
                    "Sandbox worker exited unexpectedly: {diagnostics}"
                )
            }
            Self::Worker(error) => formatter.write_str(&error.message),
        }
    }
}

impl std::error::Error for PoolError {}

#[derive(Debug)]
struct PoolState {
    closed: bool,
    idle: Vec<Worker>,
    total_workers: usize,
}

#[derive(Debug)]
pub struct Pool {
    options: PoolOptions,
    state: AsyncMutex<PoolState>,
    semaphore: Arc<Semaphore>,
    spawn_lock: AsyncMutex<()>,
}

impl Pool {
    pub async fn create(options: PoolOptions) -> Result<Arc<Self>, PoolError> {
        options.validate()?;
        let max_workers = options.max_workers;
        let pool = Arc::new(Self {
            options,
            state: AsyncMutex::new(PoolState {
                closed: false,
                idle: Vec::new(),
                total_workers: 0,
            }),
            semaphore: Arc::new(Semaphore::new(max_workers)),
            spawn_lock: AsyncMutex::new(()),
        });
        pool.prewarm().await?;
        Ok(pool)
    }

    pub async fn bind(self: &Arc<Self>, source: String) -> Result<RunnerLease, PoolError> {
        if self.state.lock().await.closed {
            return Err(PoolError::Closed);
        }
        let permit = timeout(
            self.options.checkout_timeout,
            self.semaphore.clone().acquire_owned(),
        )
        .await
        .map_err(|_| PoolError::CheckoutTimeout)?
        .map_err(|_| PoolError::Closed)?;
        if self.state.lock().await.closed {
            return Err(PoolError::Closed);
        }
        let mut worker = self.take_or_spawn_worker().await?;
        let bind_result = worker
            .request(
                RequestCommand::Bind { source },
                self.options.run_timeout,
                TimeoutKind::Run,
            )
            .await;
        match bind_result {
            Ok(ResponseResult::Bound) => Ok(RunnerLease {
                pool: self.clone(),
                worker: Some(worker),
                permit: Some(permit),
            }),
            Ok(other) => {
                self.discard_worker(worker).await;
                Err(PoolError::Protocol(format!(
                    "Worker returned unexpected bind response: {other:?}",
                )))
            }
            Err(error) => {
                self.discard_worker(worker).await;
                Err(error)
            }
        }
    }

    pub async fn close(&self) {
        let idle = {
            let mut state = self.state.lock().await;
            if state.closed {
                return;
            }
            state.closed = true;
            state.total_workers = state.total_workers.saturating_sub(state.idle.len());
            std::mem::take(&mut state.idle)
        };
        self.semaphore.close();
        for mut worker in idle {
            worker.shutdown().await;
        }
    }

    pub async fn idle_worker_count(&self) -> usize {
        self.state.lock().await.idle.len()
    }

    pub async fn total_worker_count(&self) -> usize {
        self.state.lock().await.total_workers
    }

    async fn prewarm(&self) -> Result<(), PoolError> {
        for _ in 0..self.options.min_workers {
            let worker = self.spawn_reserved_worker().await?;
            self.state.lock().await.idle.push(worker);
        }
        Ok(())
    }

    async fn take_or_spawn_worker(&self) -> Result<Worker, PoolError> {
        if let Some(worker) = self.state.lock().await.idle.pop() {
            return Ok(worker);
        }
        self.spawn_reserved_worker().await
    }

    async fn spawn_reserved_worker(&self) -> Result<Worker, PoolError> {
        let _spawn_guard = self.spawn_lock.lock().await;
        {
            let mut state = self.state.lock().await;
            if state.closed {
                return Err(PoolError::Closed);
            }
            if state.total_workers >= self.options.max_workers {
                return Err(PoolError::Protocol(
                    "Worker pool capacity accounting was exceeded".to_string(),
                ));
            }
            state.total_workers += 1;
        }
        match Worker::spawn(&self.options).await {
            Ok(worker) => Ok(worker),
            Err(error) => {
                self.state.lock().await.total_workers -= 1;
                Err(error)
            }
        }
    }

    async fn discard_worker(&self, mut worker: Worker) {
        worker.kill().await;
        {
            let mut state = self.state.lock().await;
            state.total_workers = state.total_workers.saturating_sub(1);
        }
        self.replenish_minimum().await;
    }

    async fn replenish_minimum(&self) {
        loop {
            let should_spawn = {
                let state = self.state.lock().await;
                !state.closed && state.total_workers < self.options.min_workers
            };
            if !should_spawn {
                return;
            }
            match self.spawn_reserved_worker().await {
                Ok(worker) => self.state.lock().await.idle.push(worker),
                Err(_) => return,
            }
        }
    }
}

pub struct RunnerLease {
    pool: Arc<Pool>,
    worker: Option<Worker>,
    permit: Option<OwnedSemaphorePermit>,
}

impl RunnerLease {
    pub async fn run(&mut self, arguments: Vec<Value>) -> Result<Value, PoolError> {
        let worker = self.worker.as_mut().ok_or(PoolError::Closed)?;
        let result = worker
            .request(
                RequestCommand::Run { arguments },
                self.pool.options.run_timeout,
                TimeoutKind::Run,
            )
            .await;
        match result {
            Ok(ResponseResult::Value { value }) => Ok(value),
            Ok(other) => {
                self.discard().await;
                Err(PoolError::Protocol(format!(
                    "Worker returned unexpected run response: {other:?}",
                )))
            }
            Err(error) if error.poisons_worker() => {
                self.discard().await;
                Err(error)
            }
            Err(error) => Err(error),
        }
    }

    pub async fn close(&mut self) {
        let Some(mut worker) = self.worker.take() else {
            return;
        };
        let clean = matches!(
            worker
                .request(
                    RequestCommand::Reset,
                    self.pool.options.run_timeout,
                    TimeoutKind::Run,
                )
                .await,
            Ok(ResponseResult::Reset)
        );
        if clean {
            worker.clean_checkouts += 1;
            if worker.clean_checkouts >= self.pool.options.recycle_after
                || self.pool.state.lock().await.closed
            {
                self.pool.discard_worker(worker).await;
            } else {
                self.pool.state.lock().await.idle.push(worker);
            }
        } else {
            self.pool.discard_worker(worker).await;
        }
        self.permit.take();
    }

    pub async fn discard(&mut self) {
        if let Some(worker) = self.worker.take() {
            self.pool.discard_worker(worker).await;
        }
        self.permit.take();
    }

    pub fn is_closed(&self) -> bool {
        self.worker.is_none()
    }

    pub fn process_id(&self) -> Option<u32> {
        self.worker.as_ref().and_then(|worker| worker.child.id())
    }
}

impl Drop for RunnerLease {
    fn drop(&mut self) {
        let Some(mut worker) = self.worker.take() else {
            return;
        };
        self.permit.take();
        if let Ok(handle) = tokio::runtime::Handle::try_current() {
            let pool = self.pool.clone();
            handle.spawn(async move {
                pool.discard_worker(worker).await;
            });
        } else {
            worker.start_kill();
        }
    }
}

#[derive(Clone, Copy)]
enum TimeoutKind {
    Startup,
    Run,
}

#[derive(Debug)]
struct Worker {
    child: Child,
    stdin: ChildStdin,
    stdout: BufReader<ChildStdout>,
    stderr_tail: Arc<Mutex<VecDeque<u8>>>,
    stderr_task: JoinHandle<()>,
    _working_directory: TempDir,
    next_request_id: u64,
    clean_checkouts: u64,
}

impl Worker {
    async fn spawn(options: &PoolOptions) -> Result<Self, PoolError> {
        let working_directory = tempfile::Builder::new()
            .prefix("belgie-runtime-")
            .tempdir()
            .map_err(|error| PoolError::Spawn(error.to_string()))?;
        let mut command = Command::new(&options.worker_path);
        command
            .arg("--max-old-generation-size-mb")
            .arg(options.max_old_generation_size_mb.to_string())
            .env_clear()
            .current_dir(working_directory.path())
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .kill_on_drop(true);
        let mut child = command.spawn().map_err(|error| {
            PoolError::Spawn(format!(
                "Could not spawn sandbox worker at {}: {error}",
                options.worker_path.display(),
            ))
        })?;
        let stdin = child
            .stdin
            .take()
            .ok_or_else(|| PoolError::Spawn("Worker stdin was not piped".to_string()))?;
        let stdout = child
            .stdout
            .take()
            .ok_or_else(|| PoolError::Spawn("Worker stdout was not piped".to_string()))?;
        let stderr = child
            .stderr
            .take()
            .ok_or_else(|| PoolError::Spawn("Worker stderr was not piped".to_string()))?;
        let stderr_tail = Arc::new(Mutex::new(VecDeque::with_capacity(STDERR_TAIL_BYTES)));
        let stderr_task = tokio::spawn(capture_stderr(stderr, stderr_tail.clone()));
        let mut worker = Self {
            child,
            stdin,
            stdout: BufReader::new(stdout),
            stderr_tail,
            stderr_task,
            _working_directory: working_directory,
            next_request_id: 1,
            clean_checkouts: 0,
        };
        match worker
            .request(RequestCommand::Ping, STARTUP_TIMEOUT, TimeoutKind::Startup)
            .await
        {
            Ok(ResponseResult::Pong) => Ok(worker),
            Ok(other) => {
                worker.kill().await;
                Err(PoolError::Protocol(format!(
                    "Worker returned unexpected startup response: {other:?}",
                )))
            }
            Err(error) => {
                worker.kill().await;
                Err(error)
            }
        }
    }

    async fn request(
        &mut self,
        command: RequestCommand,
        duration: Duration,
        timeout_kind: TimeoutKind,
    ) -> Result<ResponseResult, PoolError> {
        let request_id = self.next_request_id;
        self.next_request_id = self
            .next_request_id
            .checked_add(1)
            .ok_or_else(|| PoolError::Protocol("Worker request ID overflowed".to_string()))?;
        let request = Request::new(request_id, command);
        let result = timeout(duration, self.exchange(request_id, request)).await;
        match result {
            Ok(result) => result,
            Err(_) => match timeout_kind {
                TimeoutKind::Startup => Err(PoolError::Spawn(
                    "Timed out starting sandbox worker".to_string(),
                )),
                TimeoutKind::Run => Err(PoolError::RunTimeout),
            },
        }
    }

    async fn exchange(
        &mut self,
        request_id: u64,
        request: Request,
    ) -> Result<ResponseResult, PoolError> {
        let frame =
            encode_frame(&request).map_err(|error| PoolError::Protocol(error.to_string()))?;
        self.stdin
            .write_all(&frame)
            .await
            .map_err(|_| self.crash_error())?;
        self.stdin.flush().await.map_err(|_| self.crash_error())?;
        let mut length = [0_u8; 4];
        self.stdout
            .read_exact(&mut length)
            .await
            .map_err(|_| self.crash_error())?;
        let size = u32::from_be_bytes(length) as usize;
        if size > MAX_FRAME_SIZE {
            return Err(PoolError::Protocol(format!(
                "Worker frame size {size} exceeds the {MAX_FRAME_SIZE}-byte limit",
            )));
        }
        let mut payload = vec![0_u8; size];
        self.stdout
            .read_exact(&mut payload)
            .await
            .map_err(|_| self.crash_error())?;
        let response: Response =
            decode_payload(&payload).map_err(|error| PoolError::Protocol(error.to_string()))?;
        validate_response(response, request_id)
    }

    fn crash_error(&mut self) -> PoolError {
        let diagnostics = self.stderr_diagnostics();
        let status = self
            .child
            .try_wait()
            .ok()
            .flatten()
            .map(|status| format!("exit status {status}"));
        let diagnostics = [status, (!diagnostics.is_empty()).then_some(diagnostics)]
            .into_iter()
            .flatten()
            .collect::<Vec<_>>()
            .join("; ");
        PoolError::WorkerCrash { diagnostics }
    }

    fn stderr_diagnostics(&self) -> String {
        let mut tail = self
            .stderr_tail
            .lock()
            .expect("stderr tail lock should not be poisoned");
        String::from_utf8_lossy(tail.make_contiguous())
            .trim()
            .to_string()
    }

    async fn shutdown(&mut self) {
        let _ = self
            .request(
                RequestCommand::Shutdown,
                STARTUP_TIMEOUT,
                TimeoutKind::Startup,
            )
            .await;
        let _ = self.child.wait().await;
        self.stderr_task.abort();
    }

    async fn kill(&mut self) {
        let _ = self.child.kill().await;
        let _ = self.child.wait().await;
        self.stderr_task.abort();
    }

    fn start_kill(&mut self) {
        let _ = self.child.start_kill();
        self.stderr_task.abort();
    }
}

fn validate_response(response: Response, request_id: u64) -> Result<ResponseResult, PoolError> {
    if response.version != PROTOCOL_VERSION {
        return Err(PoolError::Protocol(format!(
            "Worker protocol version {} does not match {PROTOCOL_VERSION}",
            response.version,
        )));
    }
    if response.request_id != request_id {
        return Err(PoolError::Protocol(format!(
            "Worker response ID {} does not match request ID {request_id}",
            response.request_id,
        )));
    }
    match response.outcome {
        ResponseOutcome::Success { result } => Ok(result),
        ResponseOutcome::Failure { error } => Err(PoolError::Worker(error)),
    }
}

async fn capture_stderr(mut stderr: ChildStderr, tail: Arc<Mutex<VecDeque<u8>>>) {
    let mut buffer = [0_u8; 1024];
    loop {
        let Ok(count) = stderr.read(&mut buffer).await else {
            return;
        };
        if count == 0 {
            return;
        }
        let mut tail = tail
            .lock()
            .expect("stderr tail lock should not be poisoned");
        for byte in &buffer[..count] {
            if tail.len() == STDERR_TAIL_BYTES {
                tail.pop_front();
            }
            tail.push_back(*byte);
        }
    }
}

#[cfg(test)]
mod tests {
    use belgie_protocol::{PROTOCOL_VERSION, Response, ResponseResult};

    use super::{PoolError, validate_response};

    #[test]
    fn rejects_response_version_mismatches() {
        let mut response = Response::success(1, ResponseResult::Pong);
        response.version = PROTOCOL_VERSION + 1;
        assert!(matches!(
            validate_response(response, 1),
            Err(PoolError::Protocol(_))
        ));
    }

    #[test]
    fn rejects_response_request_id_mismatches() {
        let response = Response::success(2, ResponseResult::Pong);
        assert!(matches!(
            validate_response(response, 1),
            Err(PoolError::Protocol(_))
        ));
    }
}
