use std::io::{BufReader, BufWriter};

use belgie_core::{JsValue, SandboxError, SandboxErrorKind, SandboxOptions, SandboxSession};
use belgie_protocol::{
    PROTOCOL_VERSION, Request, RequestCommand, Response, ResponseResult, WorkerError,
    WorkerErrorKind, read_frame, write_frame,
};

const DEFAULT_HEAP_LIMIT_MB: u64 = 128;

fn main() {
    let heap_limit = parse_heap_limit();
    let runtime = tokio::runtime::Builder::new_current_thread()
        .build()
        .expect("worker async runtime should initialize");
    let stdin = std::io::stdin();
    let stdout = std::io::stdout();
    let mut reader = BufReader::new(stdin.lock());
    let mut writer = BufWriter::new(stdout.lock());
    let mut session = None;

    loop {
        let request: Request = match read_frame(&mut reader) {
            Ok(request) => request,
            Err(error) => {
                eprintln!("worker protocol read failed: {error}");
                return;
            }
        };
        let shutdown = matches!(request.command, RequestCommand::Shutdown);
        let response = if request.version != PROTOCOL_VERSION {
            Response::failure(
                request.request_id,
                WorkerError::protocol(
                    "version_mismatch",
                    format!(
                        "Worker protocol version {} does not match {PROTOCOL_VERSION}",
                        request.version,
                    ),
                ),
            )
        } else {
            handle_request(&runtime, &mut session, heap_limit, request)
        };
        if let Err(error) = write_frame(&mut writer, &response) {
            eprintln!("worker protocol write failed: {error}");
            return;
        }
        if shutdown {
            return;
        }
    }
}

fn handle_request(
    runtime: &tokio::runtime::Runtime,
    session: &mut Option<SandboxSession>,
    heap_limit: u64,
    request: Request,
) -> Response {
    let request_id = request.request_id;
    let result = match request.command {
        RequestCommand::Ping => Ok(ResponseResult::Pong),
        RequestCommand::Bind { source } => {
            if session.is_some() {
                Err(WorkerError::protocol(
                    "already_bound",
                    "Worker is already bound to a script",
                ))
            } else {
                runtime
                    .block_on(SandboxSession::create(
                        &source,
                        SandboxOptions {
                            max_old_generation_size_mb: heap_limit,
                        },
                    ))
                    .map(|created| {
                        *session = Some(created);
                        ResponseResult::Bound
                    })
                    .map_err(worker_error)
            }
        }
        RequestCommand::Run { arguments } => match session.as_mut() {
            Some(session) => arguments
                .into_iter()
                .map(JsValue::from_json)
                .collect::<Result<Vec<_>, _>>()
                .and_then(|arguments| runtime.block_on(session.run(arguments)))
                .map(|value| ResponseResult::Value {
                    value: value.into_json(),
                })
                .map_err(worker_error),
            None => Err(WorkerError::protocol(
                "not_bound",
                "Worker has not been bound to a script",
            )),
        },
        RequestCommand::Reset => {
            *session = None;
            Ok(ResponseResult::Reset)
        }
        RequestCommand::Shutdown => {
            *session = None;
            Ok(ResponseResult::Shutdown)
        }
    };
    match result {
        Ok(result) => Response::success(request_id, result),
        Err(error) => Response::failure(request_id, error),
    }
}

fn worker_error(error: SandboxError) -> WorkerError {
    WorkerError {
        kind: match error.kind {
            SandboxErrorKind::Runtime => WorkerErrorKind::Runtime,
            SandboxErrorKind::Module => WorkerErrorKind::Module,
            SandboxErrorKind::JavaScript => WorkerErrorKind::JavaScript,
            SandboxErrorKind::Value => WorkerErrorKind::Value,
        },
        code: error.code,
        message: error.message,
    }
}

fn parse_heap_limit() -> u64 {
    let mut arguments = std::env::args().skip(1);
    while let Some(argument) = arguments.next() {
        if argument == "--max-old-generation-size-mb" {
            return arguments
                .next()
                .and_then(|value| value.parse().ok())
                .unwrap_or(DEFAULT_HEAP_LIMIT_MB);
        }
    }
    DEFAULT_HEAP_LIMIT_MB
}
