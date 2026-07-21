use std::path::{Path, PathBuf};
use std::rc::Rc;
use std::sync::OnceLock;

use deno_core::ModuleSpecifier;
use deno_lib::worker::{LibMainWorker, LibWorkerFactoryRoots};

use crate::embed::sys::EmbedSys;
use crate::embed::{EmbedContext, EmbedContextOptions, init::spawn_v8_worker};
use crate::options::{JsRuntimeOptions, RuntimeWorkerOptions};
use crate::runtime::package_worker::{self, BoundPackageWorkerOptions};
use crate::types::error::BindingError;

static CHILD_PROCESS_EXECUTABLE: OnceLock<PathBuf> = OnceLock::new();

pub(crate) fn set_executable(path: PathBuf) {
    let _ = CHILD_PROCESS_EXECUTABLE.set(path);
}

pub(crate) fn configure_worker(worker: &mut LibMainWorker) -> Result<(), BindingError> {
    let Some(executable) = CHILD_PROCESS_EXECUTABLE.get() else {
        return Ok(());
    };
    let executable = serde_json::to_string(&executable.to_string_lossy())
        .map_err(|error| BindingError::runtime(error.to_string()))?;
    worker
        .js_runtime()
        .execute_script(
            "<belgie:child-process>",
            format!(
                "globalThis.process.execPath = {executable}; globalThis.Deno.execPath = () => {executable};"
            ),
        )
        .map(|_| ())
        .map_err(|error| BindingError::runtime(error.to_string()))
}

pub(crate) fn run(module: PathBuf, argv: Vec<String>) -> Result<i32, BindingError> {
    spawn_v8_worker(move || run_on_worker_thread(&module, argv))
        .join()
        .map_err(|_| BindingError::runtime("Belgie child process worker panicked"))?
}

fn run_on_worker_thread(module: &Path, argv: Vec<String>) -> Result<i32, BindingError> {
    let runtime = tokio::runtime::Builder::new_current_thread()
        .enable_all()
        .build()
        .map_err(|error| {
            BindingError::runtime(format!("Creating child process runtime failed: {error}"))
        })?;
    runtime.block_on(run_async(module, argv))
}

async fn run_async(module: &Path, argv: Vec<String>) -> Result<i32, BindingError> {
    let cwd = std::env::current_dir().map_err(|error| {
        BindingError::runtime(format!("Resolving child process cwd failed: {error}"))
    })?;
    let main_module = ModuleSpecifier::from_file_path(module).map_err(|()| {
        BindingError::runtime(format!(
            "Could not convert child process entrypoint {} to a file URL",
            module.display()
        ))
    })?;
    let context = Rc::new(
        EmbedContext::new_with_options(
            cwd.clone(),
            cwd.join("deno.lock"),
            EmbedContextOptions::default(),
        )
        .map_err(|error| BindingError::runtime(error.to_string()))?,
    );
    let node_ipc_init = deno_lib::args::node_ipc_init(&EmbedSys::default())
        .map_err(|error| BindingError::runtime(error.to_string()))?;
    let mut worker = package_worker::create_bound_package_worker(
        context,
        cwd,
        main_module.clone(),
        BoundPackageWorkerOptions {
            argv,
            argv0: CHILD_PROCESS_EXECUTABLE
                .get()
                .map(|path| path.to_string_lossy().into_owned()),
            js_runtime_options: JsRuntimeOptions::default(),
            runtime_worker_options: RuntimeWorkerOptions::default(),
            main_source: None,
            header_overrides: crate::embed::js_content_type_header_overrides(main_module),
            node_ipc_init,
        },
        &LibWorkerFactoryRoots::default(),
    )
    .await?;
    configure_worker(&mut worker)?;
    worker
        .run()
        .await
        .map_err(|error| BindingError::runtime(error.to_string()))
}
