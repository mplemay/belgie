use std::{collections::BTreeMap, path::PathBuf};

use deno_cache_dir::file_fetcher::CacheSetting;
use deno_config::deno_json::{NodeModulesDirMode, NodeModulesLinkerMode};
use deno_npm_installer::graph::NpmCachingStrategy;
use deno_resolver::loader::AllowJsonImports;
use pyo3::{
    Bound, PyAny, PyErr, PyResult, Python,
    exceptions::{PyBaseException, PyTypeError, PyValueError},
    prelude::*,
    types::{PyTraceback, PyType},
};

use crate::{
    binding::{blocking, normalize, packages},
    environment::{EnvironmentDefinition, SharedEnvironment},
    options::EnvironmentOptions,
    utils::normalize_path,
};

#[pyclass(
    name = "EnvironmentOptions",
    module = "belgie._core",
    skip_from_py_object
)]
#[derive(Clone, Debug)]
pub struct PyEnvironmentOptions {
    inner: EnvironmentOptions,
    cache_setting: String,
    allow_json_imports: String,
    node_modules_dir: Option<String>,
    node_modules_linker: Option<String>,
    npm_caching: String,
}

#[pyclass(name = "Environment", module = "belgie._core", skip_from_py_object)]
#[derive(Clone, Debug)]
pub struct PyEnvironment {
    inner: SharedEnvironment,
}

#[pyclass(name = "SyncEnvironment", module = "belgie._core", skip_from_py_object)]
#[derive(Clone, Debug)]
pub struct PySyncEnvironment {
    inner: SharedEnvironment,
}

#[pyclass(
    name = "AsyncEnvironment",
    module = "belgie._core",
    skip_from_py_object
)]
#[derive(Clone, Debug)]
pub struct PyAsyncEnvironment {
    inner: SharedEnvironment,
}

#[pymethods]
impl PyEnvironmentOptions {
    #[new]
    #[pyo3(signature = (*, cache_setting = "use", reload = None, allow_remote = true, allow_json_imports = "with_attribute", node_modules_dir = None, node_modules_linker = None, npm_caching = "eager", no_npm = false, clean_on_install = true, production = false, skip_types = false, unsafely_ignore_certificate_errors = None, import_package_lockfile = false, minimum_dependency_age_minutes = None))]
    #[allow(clippy::too_many_arguments)]
    fn new(
        cache_setting: &str,
        reload: Option<Vec<String>>,
        allow_remote: bool,
        allow_json_imports: &str,
        node_modules_dir: Option<&str>,
        node_modules_linker: Option<&str>,
        npm_caching: &str,
        no_npm: bool,
        clean_on_install: bool,
        production: bool,
        skip_types: bool,
        unsafely_ignore_certificate_errors: Option<&Bound<'_, PyAny>>,
        import_package_lockfile: bool,
        minimum_dependency_age_minutes: Option<i64>,
    ) -> PyResult<Self> {
        let cache_setting = normalize_cache_setting(cache_setting, reload)?;
        let allow_json_imports = normalize_allow_json_imports(allow_json_imports)?;
        let node_modules_dir = normalize_node_modules_dir(node_modules_dir)?;
        let node_modules_linker = normalize_node_modules_linker(node_modules_linker)?;
        let npm_caching = normalize_npm_caching(npm_caching)?;
        let minimum_dependency_age_minutes = normalize::normalize_non_negative_u64(
            "minimum_dependency_age_minutes",
            minimum_dependency_age_minutes,
        )?;
        Ok(Self {
            inner: EnvironmentOptions::new(
                cache_setting.0,
                allow_remote,
                allow_json_imports.0,
                node_modules_dir.as_ref().map(|value| value.0),
                node_modules_linker.as_ref().map(|value| value.0),
                npm_caching.0,
                no_npm,
                clean_on_install,
                production,
                skip_types,
                normalize_certificate_errors(unsafely_ignore_certificate_errors)?,
                import_package_lockfile,
                minimum_dependency_age_minutes,
            ),
            cache_setting: cache_setting.1,
            allow_json_imports: allow_json_imports.1,
            node_modules_dir: node_modules_dir.map(|value| value.1),
            node_modules_linker: node_modules_linker.map(|value| value.1),
            npm_caching: npm_caching.1,
        })
    }

    fn __repr__(&self) -> String {
        format!(
            "EnvironmentOptions(cache_setting={:?}, allow_json_imports={:?}, node_modules_dir={:?}, node_modules_linker={:?}, npm_caching={:?}, import_package_lockfile={:?}, minimum_dependency_age_minutes={:?})",
            self.cache_setting,
            self.allow_json_imports,
            self.node_modules_dir,
            self.node_modules_linker,
            self.npm_caching,
            self.inner.import_package_lockfile(),
            self.inner.minimum_dependency_age_minutes(),
        )
    }
}

#[pymethods]
impl PyEnvironment {
    #[new]
    #[pyo3(signature = (dependencies = None, *, path = None, lockfile = None, cache = None, options = None))]
    fn new(
        py: Python<'_>,
        dependencies: Option<BTreeMap<String, String>>,
        path: Option<PathBuf>,
        lockfile: Option<PathBuf>,
        cache: Option<PathBuf>,
        options: Option<PyRef<'_, PyEnvironmentOptions>>,
    ) -> PyResult<Self> {
        let dependencies = dependencies.unwrap_or_default();
        if dependencies.is_empty() && lockfile.is_some() {
            return Err(PyValueError::new_err(
                "lockfile requires at least one dependency mapping",
            ));
        }
        let lockfile = normalize_lockfile_arg(py, lockfile, LockfilePathMode::Input)?;
        let persist_path = normalize_path::normalize_optional_directory(py, path)?;
        let cache = normalize_path::normalize_optional_output_directory(py, cache, "cache")?;
        let workspace = match &persist_path {
            Some(path) => path.clone(),
            None => normalize_path::normalize_cwd(py, None)?,
        };
        let definition = EnvironmentDefinition::from_mapping_with_options(
            workspace,
            persist_path,
            dependencies,
            lockfile,
            cache,
            options
                .as_deref()
                .map(PyEnvironmentOptions::environment_options)
                .unwrap_or_default(),
        )
        .map_err(blocking::any_error_to_py)?;
        Ok(Self {
            inner: SharedEnvironment::new(definition),
        })
    }

    fn __enter__(&self, py: Python<'_>) -> PyResult<PySyncEnvironment> {
        let environment = self.inner.clone();
        py.detach(|| environment.activate_blocking())
            .map_err(blocking::any_error_to_py)?;
        Ok(PySyncEnvironment::new(environment))
    }

    fn __exit__(
        &self,
        _exc_type: Option<&Bound<'_, PyType>>,
        _exc: Option<&Bound<'_, PyBaseException>>,
        _traceback: Option<&Bound<'_, PyTraceback>>,
    ) -> PyResult<bool> {
        self.inner.deactivate().map_err(blocking::any_error_to_py)?;
        Ok(false)
    }

    fn __aenter__<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyAny>> {
        let environment = self.inner.clone();
        let result = PyAsyncEnvironment::new(environment.clone());
        pyo3_async_runtimes::tokio::future_into_py(py, async move {
            blocking::run_on_blocking_thread(
                move || environment.activate_blocking().map(|_| ()),
                "Belgie environment activation failed",
            )
            .await?;
            Ok(result)
        })
    }

    fn __aexit__<'py>(
        &self,
        py: Python<'py>,
        _exc_type: Option<&Bound<'_, PyType>>,
        _exc: Option<&Bound<'_, PyBaseException>>,
        _traceback: Option<&Bound<'_, PyTraceback>>,
    ) -> PyResult<Bound<'py, PyAny>> {
        let environment = self.inner.clone();
        pyo3_async_runtimes::tokio::future_into_py(py, async move {
            environment
                .deactivate()
                .map_err(blocking::any_error_to_py)?;
            Ok(false)
        })
    }

    fn __repr__(&self) -> String {
        environment_repr(&self.inner, "Environment")
    }
}

#[pymethods]
impl PySyncEnvironment {
    #[pyo3(signature = (*, lockfile = None))]
    fn lock(
        &self,
        py: Python<'_>,
        lockfile: Option<PathBuf>,
    ) -> PyResult<packages::PyEnvironmentInstallResult> {
        let output_lockfile = normalize_lockfile_arg(py, lockfile, LockfilePathMode::Output)?;
        let environment = self.inner.clone();
        py.detach(|| environment.lock_blocking(output_lockfile))
            .map(Into::into)
            .map_err(blocking::any_error_to_py)
    }

    fn install(&self, py: Python<'_>) -> PyResult<packages::PyEnvironmentInstallResult> {
        let environment = self.inner.clone();
        py.detach(|| environment.install_blocking())
            .map(Into::into)
            .map_err(blocking::any_error_to_py)
    }

    #[pyo3(signature = (packages = None, *, latest = false, lockfile_only = false))]
    fn update(
        &self,
        py: Python<'_>,
        packages: Option<Vec<String>>,
        latest: bool,
        lockfile_only: bool,
    ) -> PyResult<packages::PyEnvironmentUpdateResult> {
        let filters = packages.unwrap_or_default();
        let environment = self.inner.clone();
        py.detach(|| environment.update_blocking(filters, latest, lockfile_only))
            .map(Into::into)
            .map_err(blocking::any_error_to_py)
    }

    fn __repr__(&self) -> String {
        environment_repr(&self.inner, "SyncEnvironment")
    }
}

#[pymethods]
impl PyAsyncEnvironment {
    #[pyo3(signature = (*, lockfile = None))]
    fn lock<'py>(&self, py: Python<'py>, lockfile: Option<PathBuf>) -> PyResult<Bound<'py, PyAny>> {
        let output_lockfile = normalize_lockfile_arg(py, lockfile, LockfilePathMode::Output)?;
        let environment = self.inner.clone();
        pyo3_async_runtimes::tokio::future_into_py(py, async move {
            let result = blocking::run_on_blocking_thread(
                move || environment.lock_blocking(output_lockfile),
                "Belgie environment lock failed",
            )
            .await?;
            Ok(packages::PyEnvironmentInstallResult::from(result))
        })
    }

    fn install<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyAny>> {
        let environment = self.inner.clone();
        pyo3_async_runtimes::tokio::future_into_py(py, async move {
            let result = blocking::run_on_blocking_thread(
                move || environment.install_blocking(),
                "Belgie environment install failed",
            )
            .await?;
            Ok(packages::PyEnvironmentInstallResult::from(result))
        })
    }

    #[pyo3(signature = (packages = None, *, latest = false, lockfile_only = false))]
    fn update<'py>(
        &self,
        py: Python<'py>,
        packages: Option<Vec<String>>,
        latest: bool,
        lockfile_only: bool,
    ) -> PyResult<Bound<'py, PyAny>> {
        let filters = packages.unwrap_or_default();
        let environment = self.inner.clone();
        pyo3_async_runtimes::tokio::future_into_py(py, async move {
            let result = blocking::run_on_blocking_thread(
                move || environment.update_blocking(filters, latest, lockfile_only),
                "Belgie environment update failed",
            )
            .await?;
            Ok(packages::PyEnvironmentUpdateResult::from(result))
        })
    }

    fn __repr__(&self) -> String {
        environment_repr(&self.inner, "AsyncEnvironment")
    }
}

impl PyEnvironment {
    pub(crate) fn environment(&self) -> SharedEnvironment {
        self.inner.clone()
    }
}

impl PyEnvironmentOptions {
    pub(crate) fn environment_options(&self) -> EnvironmentOptions {
        self.inner.clone()
    }
}

impl PySyncEnvironment {
    fn new(environment: SharedEnvironment) -> Self {
        Self { inner: environment }
    }

    pub(crate) fn environment(&self) -> SharedEnvironment {
        self.inner.clone()
    }
}

impl PyAsyncEnvironment {
    fn new(environment: SharedEnvironment) -> Self {
        Self { inner: environment }
    }

    pub(crate) fn environment(&self) -> SharedEnvironment {
        self.inner.clone()
    }
}

enum LockfilePathMode {
    Input,
    Output,
}

fn normalize_lockfile_arg(
    py: Python<'_>,
    lockfile: Option<PathBuf>,
    mode: LockfilePathMode,
) -> PyResult<Option<std::path::PathBuf>> {
    let Some(path) = lockfile else {
        return Ok(None);
    };
    match mode {
        LockfilePathMode::Input => normalize_path::normalize_file(py, path, "lockfile").map(Some),
        LockfilePathMode::Output => {
            normalize_path::normalize_output_file(py, path, "lockfile").map(Some)
        }
    }
}

fn environment_repr(environment: &SharedEnvironment, class_name: &str) -> String {
    let active = if environment.is_active() {
        "True"
    } else {
        "False"
    };
    match environment.persist_path() {
        Some(path) => format!(
            "{class_name}(path={}, dependencies={}, active={active})",
            path.display(),
            environment.dependency_count(),
        ),
        None => format!(
            "{class_name}(path=None, workspace={}, dependencies={}, active={active})",
            environment.workspace().display(),
            environment.dependency_count(),
        ),
    }
}

fn normalize_cache_setting(
    cache_setting: &str,
    reload: Option<Vec<String>>,
) -> PyResult<(CacheSetting, String)> {
    match (cache_setting, reload) {
        ("use", None) => Ok((CacheSetting::Use, "use".to_string())),
        ("only", None) => Ok((CacheSetting::Only, "only".to_string())),
        ("reload", None) => Ok((CacheSetting::ReloadAll, "reload".to_string())),
        ("reload", Some(values)) => Ok((CacheSetting::ReloadSome(values), "reload".to_string())),
        ("use" | "only", Some(_)) => Err(PyValueError::new_err(
            "reload requires cache_setting='reload'",
        )),
        (value, _) => Err(invalid_option(
            "cache_setting",
            value,
            "use, reload, or only",
        )),
    }
}

fn normalize_allow_json_imports(value: &str) -> PyResult<(AllowJsonImports, String)> {
    match value {
        "with_attribute" => Ok((AllowJsonImports::WithAttribute, value.to_string())),
        "always" => Ok((AllowJsonImports::Always, value.to_string())),
        value => Err(invalid_option(
            "allow_json_imports",
            value,
            "with_attribute or always",
        )),
    }
}

fn normalize_node_modules_dir(
    value: Option<&str>,
) -> PyResult<Option<(NodeModulesDirMode, String)>> {
    match value {
        None => Ok(None),
        Some("auto") => Ok(Some((NodeModulesDirMode::Auto, "auto".to_string()))),
        Some("manual") => Ok(Some((NodeModulesDirMode::Manual, "manual".to_string()))),
        Some("none") => Ok(Some((NodeModulesDirMode::None, "none".to_string()))),
        Some(value) => Err(invalid_option(
            "node_modules_dir",
            value,
            "auto, manual, or none",
        )),
    }
}

fn normalize_node_modules_linker(
    value: Option<&str>,
) -> PyResult<Option<(NodeModulesLinkerMode, String)>> {
    match value {
        None => Ok(None),
        Some("isolated") => Ok(Some((
            NodeModulesLinkerMode::Isolated,
            "isolated".to_string(),
        ))),
        Some("hoisted") => Ok(Some((
            NodeModulesLinkerMode::Hoisted,
            "hoisted".to_string(),
        ))),
        Some(value) => Err(invalid_option(
            "node_modules_linker",
            value,
            "isolated or hoisted",
        )),
    }
}

fn normalize_npm_caching(value: &str) -> PyResult<(NpmCachingStrategy, String)> {
    match value {
        "eager" => Ok((NpmCachingStrategy::Eager, value.to_string())),
        "lazy" => Ok((NpmCachingStrategy::Lazy, value.to_string())),
        "manual" => Ok((NpmCachingStrategy::Manual, value.to_string())),
        value => Err(invalid_option(
            "npm_caching",
            value,
            "eager, lazy, or manual",
        )),
    }
}

fn normalize_certificate_errors(value: Option<&Bound<'_, PyAny>>) -> PyResult<Option<Vec<String>>> {
    let Some(value) = value else {
        return Ok(None);
    };
    if let Ok(ignore_all) = value.extract::<bool>() {
        return Ok(ignore_all.then(Vec::new));
    }
    value.extract::<Vec<String>>().map(Some).map_err(|_| {
        PyTypeError::new_err("unsafely_ignore_certificate_errors must be bool or iterable of str")
    })
}

fn invalid_option(field_name: &str, value: &str, expected: &str) -> PyErr {
    PyValueError::new_err(format!(
        "{field_name} must be one of: {expected}; got {value:?}"
    ))
}
