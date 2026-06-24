use std::{
    fs, io,
    path::{Path, PathBuf},
};

use pyo3::{
    Bound, PyAny, PyResult, Python,
    exceptions::{PyFileNotFoundError, PyOSError, PyTypeError},
    types::PyAnyMethods,
};

pub fn path_from_py(value: &Bound<'_, PyAny>, argument_name: &str) -> PyResult<PathBuf> {
    let py = value.py();
    let os = py.import("os")?;
    let fspath = os.getattr("fspath")?.call1((value,))?;
    let path = fspath.extract::<String>().map_err(|_| {
        PyTypeError::new_err(format!("{argument_name} must be str or os.PathLike[str]"))
    })?;
    Ok(PathBuf::from(path))
}

pub fn normalize_cwd(py: Python<'_>, cwd: Option<&Bound<'_, PyAny>>) -> PyResult<PathBuf> {
    let path = match cwd {
        Some(value) if !value.is_none() => path_from_py(value, "cwd")?,
        _ => std::env::current_dir().map_err(io_error_to_py)?,
    };
    normalize_directory(py, path, "cwd")
}

pub fn normalize_optional_output_directory(
    py: Python<'_>,
    path: Option<&Bound<'_, PyAny>>,
    argument_name: &str,
) -> PyResult<Option<PathBuf>> {
    let Some(value) = path.filter(|value| !value.is_none()) else {
        return Ok(None);
    };
    let path = path_from_py(value, argument_name)?;
    normalize_output_directory(py, path, argument_name).map(Some)
}

pub fn normalize_optional_directory(
    py: Python<'_>,
    path: Option<&Bound<'_, PyAny>>,
) -> PyResult<Option<PathBuf>> {
    let Some(value) = path.filter(|value| !value.is_none()) else {
        return Ok(None);
    };
    let path = path_from_py(value, "path")?;
    normalize_directory(py, path, "path").map(Some)
}

pub fn normalize_directory(
    py: Python<'_>,
    path: PathBuf,
    argument_name: &str,
) -> PyResult<PathBuf> {
    let path = absolutize(py, path)?;
    if !path.exists() {
        return Err(PyFileNotFoundError::new_err(format!(
            "{argument_name} does not exist: {}",
            path.display()
        )));
    }
    if !path.is_dir() {
        return Err(PyOSError::new_err(format!(
            "{argument_name} is not a directory: {}",
            path.display()
        )));
    }
    Ok(path)
}

pub fn normalize_file(py: Python<'_>, path: PathBuf, argument_name: &str) -> PyResult<PathBuf> {
    let path = absolutize(py, path)?;
    if !path.exists() {
        return Err(PyFileNotFoundError::new_err(format!(
            "{argument_name} does not exist: {}",
            path.display()
        )));
    }
    if !path.is_file() {
        return Err(PyOSError::new_err(format!(
            "{argument_name} is not a file: {}",
            path.display()
        )));
    }
    Ok(path)
}

pub fn normalize_output_file(
    py: Python<'_>,
    path: PathBuf,
    argument_name: &str,
) -> PyResult<PathBuf> {
    let path = absolutize(py, path)?;
    if path.exists() && !path.is_file() {
        return Err(PyOSError::new_err(format!(
            "{argument_name} is not a file: {}",
            path.display()
        )));
    }
    Ok(path)
}

pub fn normalize_output_directory(
    py: Python<'_>,
    path: PathBuf,
    argument_name: &str,
) -> PyResult<PathBuf> {
    let path = absolutize(py, path)?;
    if path.exists() && !path.is_dir() {
        return Err(PyOSError::new_err(format!(
            "{argument_name} is not a directory: {}",
            path.display()
        )));
    }
    Ok(path)
}

pub fn read_script_file(py: Python<'_>, path: PathBuf) -> PyResult<(PathBuf, String)> {
    let path = absolutize(py, path)?;
    let content = fs::read_to_string(&path).map_err(io_error_to_py)?;
    Ok((path, content))
}

fn absolutize(py: Python<'_>, path: PathBuf) -> PyResult<PathBuf> {
    if path.is_absolute() {
        return Ok(path);
    }

    let cwd = std::env::current_dir().map_err(io_error_to_py)?;
    let joined = cwd.join(path);
    normalize_with_python(py, &joined)
}

fn normalize_with_python(py: Python<'_>, path: &Path) -> PyResult<PathBuf> {
    let os_path = py.import("os.path")?;
    let normalized = os_path
        .getattr("abspath")?
        .call1((path.to_string_lossy().as_ref(),))?
        .extract::<String>()?;
    Ok(PathBuf::from(normalized))
}

fn io_error_to_py(err: io::Error) -> pyo3::PyErr {
    match err.kind() {
        io::ErrorKind::NotFound => PyFileNotFoundError::new_err(err.to_string()),
        _ => PyOSError::new_err(err.to_string()),
    }
}

#[cfg(test)]
mod tests {
    use super::{
        normalize_cwd, normalize_optional_output_directory, path_from_py, read_script_file,
    };
    use pyo3::{
        IntoPyObject, Python,
        exceptions::{PyFileNotFoundError, PyOSError, PyTypeError},
        types::{PyAnyMethods, PyString},
    };
    use std::{
        env, fs, io,
        path::{Path, PathBuf},
        sync::Mutex,
        time::{SystemTime, UNIX_EPOCH},
    };

    static CWD_LOCK: Mutex<()> = Mutex::new(());

    fn with_python<R>(test: impl FnOnce(Python<'_>) -> R) -> R {
        Python::initialize();
        Python::attach(test)
    }

    fn temp_dir(name: &str) -> io::Result<PathBuf> {
        let nanos = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .expect("system clock should be after the Unix epoch")
            .as_nanos();
        let path = env::temp_dir().join(format!("belgie-{name}-{}-{nanos}", std::process::id()));
        fs::create_dir_all(&path)?;
        Ok(path)
    }

    fn remove_dir(path: &Path) {
        let _ = fs::remove_dir_all(path);
    }

    #[test]
    fn extracts_string_paths_from_python_pathlike_objects() {
        with_python(|py| {
            let pathlib = py.import("pathlib").expect("pathlib should import");
            let path = pathlib
                .getattr("Path")
                .expect("Path should exist")
                .call1(("/tmp/belgie/pathlike.ts",))
                .expect("Path construction should succeed");

            let extracted = path_from_py(&path, "path").expect("pathlike should extract");

            assert_eq!(extracted, PathBuf::from("/tmp/belgie/pathlike.ts"));
        });
    }

    #[test]
    fn rejects_non_string_pathlike_results() {
        with_python(|py| {
            let value = 42i32.into_pyobject(py).expect("integer should convert");

            let error = path_from_py(value.as_any(), "cwd").expect_err("integer path should fail");

            assert!(error.is_instance_of::<PyTypeError>(py));
            assert!(error.to_string().contains("os.PathLike"));
        });
    }

    #[test]
    fn normalizes_existing_cwd_to_an_absolute_directory() {
        let root = temp_dir("cwd-absolute").expect("temp dir should be created");

        with_python(|py| {
            let cwd = PyString::new(py, root.to_str().expect("temp path should be UTF-8"));

            let normalized = normalize_cwd(py, Some(cwd.as_any())).expect("cwd should normalize");

            assert!(normalized.is_absolute());
            assert_eq!(normalized, root);
        });

        remove_dir(&root);
    }

    #[test]
    fn rejects_missing_cwd_as_file_not_found() {
        let root = temp_dir("missing-cwd").expect("temp dir should be created");
        let missing = root.join("missing");

        with_python(|py| {
            let cwd = PyString::new(py, missing.to_str().expect("temp path should be UTF-8"));

            let error = normalize_cwd(py, Some(cwd.as_any())).expect_err("missing cwd should fail");

            assert!(error.is_instance_of::<PyFileNotFoundError>(py));
            assert!(error.to_string().contains("cwd does not exist"));
        });

        remove_dir(&root);
    }

    #[test]
    fn rejects_file_cwd_as_os_error() {
        let root = temp_dir("file-cwd").expect("temp dir should be created");
        let file_path = root.join("not-a-directory");
        fs::write(&file_path, "").expect("file should be written");

        with_python(|py| {
            let cwd = PyString::new(py, file_path.to_str().expect("temp path should be UTF-8"));

            let error = normalize_cwd(py, Some(cwd.as_any())).expect_err("file cwd should fail");

            assert!(error.is_instance_of::<PyOSError>(py));
            assert!(error.to_string().contains("cwd is not a directory"));
        });

        remove_dir(&root);
    }

    #[test]
    fn reads_utf8_script_files_and_returns_the_absolute_path() {
        let root = temp_dir("script-file").expect("temp dir should be created");
        let file_path = root.join("main.ts");
        fs::write(&file_path, "export default () => 'Deno';\n").expect("script should be written");

        with_python(|py| {
            let (normalized, content) =
                read_script_file(py, file_path.clone()).expect("script should be read");

            assert_eq!(normalized, file_path);
            assert_eq!(content, "export default () => 'Deno';\n");
        });

        remove_dir(&root);
    }

    #[test]
    fn absolutizes_relative_script_paths_against_the_current_directory() {
        let _cwd_guard = CWD_LOCK.lock().expect("cwd lock should not be poisoned");
        let root = temp_dir("relative-script").expect("temp dir should be created");
        let previous_cwd = env::current_dir().expect("current dir should be available");
        fs::write(root.join("main.ts"), "export default () => 42;\n")
            .expect("script should be written");
        env::set_current_dir(&root).expect("cwd should be set to temp dir");

        with_python(|py| {
            let (normalized, content) =
                read_script_file(py, PathBuf::from("main.ts")).expect("script should be read");
            let expected = env::current_dir()
                .expect("current dir should be available")
                .join("main.ts");

            assert_eq!(normalized, expected);
            assert_eq!(content, "export default () => 42;\n");
        });

        env::set_current_dir(previous_cwd).expect("cwd should be restored");
        remove_dir(&root);
    }

    #[test]
    fn optional_output_directory_returns_none_for_missing_argument() {
        with_python(|py| {
            let normalized = normalize_optional_output_directory(py, None, "cache")
                .expect("none should normalize");

            assert_eq!(normalized, None);
        });
    }

    #[test]
    fn optional_output_directory_absolutizes_relative_paths() {
        let _cwd_guard = CWD_LOCK.lock().expect("cwd lock should not be poisoned");
        let root = temp_dir("output-directory-relative").expect("temp dir should be created");
        let previous_cwd = env::current_dir().expect("current dir should be available");
        env::set_current_dir(&root).expect("cwd should be set to temp dir");

        with_python(|py| {
            let cache = PyString::new(py, "custom_cache");

            let normalized = normalize_optional_output_directory(py, Some(cache.as_any()), "cache")
                .expect("relative cache should normalize")
                .expect("cache should be present");

            assert!(normalized.is_absolute());
            assert_eq!(normalized, root.join("custom_cache"));
        });

        env::set_current_dir(previous_cwd).expect("cwd should be restored");
        remove_dir(&root);
    }

    #[test]
    fn optional_output_directory_allows_missing_paths() {
        let root = temp_dir("output-directory-missing").expect("temp dir should be created");
        let missing = root.join("missing-cache");

        with_python(|py| {
            let cache = PyString::new(py, missing.to_str().expect("temp path should be UTF-8"));

            let normalized = normalize_optional_output_directory(py, Some(cache.as_any()), "cache")
                .expect("missing cache should normalize")
                .expect("cache should be present");

            assert_eq!(normalized, missing);
            assert!(!normalized.exists());
        });

        remove_dir(&root);
    }

    #[test]
    fn optional_output_directory_rejects_existing_files() {
        let root = temp_dir("output-directory-file").expect("temp dir should be created");
        let file_path = root.join("not-a-directory");
        fs::write(&file_path, "").expect("file should be written");

        with_python(|py| {
            let cache = PyString::new(py, file_path.to_str().expect("temp path should be UTF-8"));

            let error = normalize_optional_output_directory(py, Some(cache.as_any()), "cache")
                .expect_err("file cache should fail");

            assert!(error.is_instance_of::<PyOSError>(py));
            assert!(error.to_string().contains("cache is not a directory"));
        });

        remove_dir(&root);
    }
}
