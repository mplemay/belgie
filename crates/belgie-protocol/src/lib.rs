use std::fmt::{Display, Formatter};
use std::io::{ErrorKind, Read, Write};

use serde::de::DeserializeOwned;
use serde::{Deserialize, Serialize};
use serde_json::Value;

pub const PROTOCOL_VERSION: u16 = 1;
pub const MAX_FRAME_SIZE: usize = 8 * 1024 * 1024;
pub const MAX_FRAME_DEPTH: usize = 64;
const PROTOCOL_ENVELOPE_DEPTH: usize = 3;

#[derive(Clone, Debug, Deserialize, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct Request {
    pub version: u16,
    pub request_id: u64,
    pub command: RequestCommand,
}

impl Request {
    pub fn new(request_id: u64, command: RequestCommand) -> Self {
        Self {
            version: PROTOCOL_VERSION,
            request_id,
            command,
        }
    }
}

#[derive(Clone, Debug, Deserialize, PartialEq, Serialize)]
#[serde(deny_unknown_fields, tag = "type", rename_all = "snake_case")]
pub enum RequestCommand {
    Ping,
    Bind { source: String },
    Run { arguments: Vec<Value> },
    Reset,
    Shutdown,
}

#[derive(Clone, Debug, Deserialize, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct Response {
    pub version: u16,
    pub request_id: u64,
    pub outcome: ResponseOutcome,
}

impl Response {
    pub fn success(request_id: u64, result: ResponseResult) -> Self {
        Self {
            version: PROTOCOL_VERSION,
            request_id,
            outcome: ResponseOutcome::Success { result },
        }
    }

    pub fn failure(request_id: u64, error: WorkerError) -> Self {
        Self {
            version: PROTOCOL_VERSION,
            request_id,
            outcome: ResponseOutcome::Failure { error },
        }
    }
}

#[derive(Clone, Debug, Deserialize, PartialEq, Serialize)]
#[serde(deny_unknown_fields, tag = "status", rename_all = "snake_case")]
pub enum ResponseOutcome {
    Success { result: ResponseResult },
    Failure { error: WorkerError },
}

#[derive(Clone, Debug, Deserialize, PartialEq, Serialize)]
#[serde(deny_unknown_fields, tag = "type", rename_all = "snake_case")]
pub enum ResponseResult {
    Pong,
    Bound,
    Value { value: Value },
    Reset,
    Shutdown,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum WorkerErrorKind {
    Runtime,
    Module,
    JavaScript,
    Value,
    Protocol,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct WorkerError {
    pub kind: WorkerErrorKind,
    pub code: String,
    pub message: String,
}

impl WorkerError {
    pub fn protocol(code: impl Into<String>, message: impl Into<String>) -> Self {
        Self {
            kind: WorkerErrorKind::Protocol,
            code: code.into(),
            message: message.into(),
        }
    }
}

#[derive(Debug)]
pub enum FrameError {
    Io(std::io::Error),
    Truncated,
    Oversized { size: usize },
    InvalidJson(String),
    ExcessiveDepth,
}

impl Display for FrameError {
    fn fmt(&self, formatter: &mut Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::Io(error) => write!(formatter, "protocol I/O failed: {error}"),
            Self::Truncated => formatter.write_str("protocol frame was truncated"),
            Self::Oversized { size } => write!(
                formatter,
                "protocol frame size {size} exceeds the {MAX_FRAME_SIZE}-byte limit",
            ),
            Self::InvalidJson(error) => {
                write!(formatter, "protocol frame is invalid JSON: {error}")
            }
            Self::ExcessiveDepth => write!(
                formatter,
                "protocol frame exceeds the maximum depth of {MAX_FRAME_DEPTH}",
            ),
        }
    }
}

impl std::error::Error for FrameError {}

pub fn read_frame<R: Read, T: DeserializeOwned>(reader: &mut R) -> Result<T, FrameError> {
    let mut length = [0_u8; 4];
    read_exact(reader, &mut length, true)?;
    let size = u32::from_be_bytes(length) as usize;
    if size > MAX_FRAME_SIZE {
        return Err(FrameError::Oversized { size });
    }
    let mut payload = vec![0_u8; size];
    read_exact(reader, &mut payload, false)?;
    decode_payload(&payload)
}

pub fn write_frame<W: Write, T: Serialize>(writer: &mut W, message: &T) -> Result<(), FrameError> {
    let frame = encode_frame(message)?;
    writer.write_all(&frame).map_err(FrameError::Io)?;
    writer.flush().map_err(FrameError::Io)
}

pub fn encode_frame<T: Serialize>(message: &T) -> Result<Vec<u8>, FrameError> {
    let payload =
        serde_json::to_vec(message).map_err(|error| FrameError::InvalidJson(error.to_string()))?;
    if payload.len() > MAX_FRAME_SIZE {
        return Err(FrameError::Oversized {
            size: payload.len(),
        });
    }
    let length = u32::try_from(payload.len())
        .map_err(|_| FrameError::Oversized {
            size: payload.len(),
        })?
        .to_be_bytes();
    let mut frame = Vec::with_capacity(4 + payload.len());
    frame.extend_from_slice(&length);
    frame.extend_from_slice(&payload);
    Ok(frame)
}

pub fn decode_payload<T: DeserializeOwned>(payload: &[u8]) -> Result<T, FrameError> {
    if payload.len() > MAX_FRAME_SIZE {
        return Err(FrameError::Oversized {
            size: payload.len(),
        });
    }
    let value: Value = serde_json::from_slice(payload)
        .map_err(|error| FrameError::InvalidJson(error.to_string()))?;
    validate_depth(&value, 0)?;
    serde_json::from_value(value).map_err(|error| FrameError::InvalidJson(error.to_string()))
}

fn read_exact<R: Read>(
    reader: &mut R,
    buffer: &mut [u8],
    allow_clean_eof: bool,
) -> Result<(), FrameError> {
    let mut read = 0;
    while read < buffer.len() {
        match reader.read(&mut buffer[read..]) {
            Ok(0) if read == 0 && allow_clean_eof => {
                return Err(FrameError::Io(std::io::Error::new(
                    ErrorKind::UnexpectedEof,
                    "worker protocol stream closed",
                )));
            }
            Ok(0) => return Err(FrameError::Truncated),
            Ok(count) => read += count,
            Err(error) if error.kind() == ErrorKind::Interrupted => {}
            Err(error) => return Err(FrameError::Io(error)),
        }
    }
    Ok(())
}

fn validate_depth(value: &Value, depth: usize) -> Result<(), FrameError> {
    if depth > MAX_FRAME_DEPTH + PROTOCOL_ENVELOPE_DEPTH {
        return Err(FrameError::ExcessiveDepth);
    }
    match value {
        Value::Array(values) => {
            for value in values {
                validate_depth(value, depth + 1)?;
            }
        }
        Value::Object(values) => {
            for value in values.values() {
                validate_depth(value, depth + 1)?;
            }
        }
        _ => {}
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use std::io::Cursor;

    use serde_json::json;

    use super::{FrameError, MAX_FRAME_SIZE, Request, RequestCommand, read_frame, write_frame};

    #[test]
    fn round_trips_a_frame() {
        let request = Request::new(
            42,
            RequestCommand::Run {
                arguments: vec![json!({"value": 21})],
            },
        );
        let mut bytes = Vec::new();
        write_frame(&mut bytes, &request).expect("frame should encode");
        assert_eq!(
            read_frame::<_, Request>(&mut Cursor::new(bytes)).expect("frame should decode"),
            request,
        );
    }

    #[test]
    fn rejects_oversized_frames_before_allocation() {
        let bytes = u32::try_from(MAX_FRAME_SIZE + 1)
            .expect("frame size should fit u32")
            .to_be_bytes();
        let error = read_frame::<_, Request>(&mut Cursor::new(bytes))
            .expect_err("oversized frame should fail");
        assert!(matches!(error, FrameError::Oversized { .. }));
    }

    #[test]
    fn rejects_malformed_and_truncated_frames() {
        let mut malformed = (4_u32.to_be_bytes()).to_vec();
        malformed.extend_from_slice(b"nope");
        assert!(matches!(
            read_frame::<_, Request>(&mut Cursor::new(malformed)),
            Err(FrameError::InvalidJson(_))
        ));

        let mut truncated = (10_u32.to_be_bytes()).to_vec();
        truncated.extend_from_slice(b"{}");
        assert!(matches!(
            read_frame::<_, Request>(&mut Cursor::new(truncated)),
            Err(FrameError::Truncated)
        ));
    }

    #[test]
    fn rejects_excessive_nesting() {
        let mut value = json!(null);
        for _ in 0..65 {
            value = json!([value]);
        }
        let request = Request::new(
            1,
            RequestCommand::Run {
                arguments: vec![value],
            },
        );
        let mut bytes = Vec::new();
        write_frame(&mut bytes, &request).expect("frame should encode");
        assert!(matches!(
            read_frame::<_, Request>(&mut Cursor::new(bytes)),
            Err(FrameError::ExcessiveDepth)
        ));
    }

    #[test]
    fn rejects_unknown_fields() {
        let payload = br#"{"version":1,"request_id":1,"command":{"type":"ping"},"extra":true}"#;
        let mut bytes = u32::try_from(payload.len())
            .expect("payload length should fit u32")
            .to_be_bytes()
            .to_vec();
        bytes.extend_from_slice(payload);
        assert!(matches!(
            read_frame::<_, Request>(&mut Cursor::new(bytes)),
            Err(FrameError::InvalidJson(_))
        ));
    }
}
