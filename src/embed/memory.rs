use deno_cache_dir::file_fetcher::{File, LoadedFrom};
use deno_core::url::Url;
use deno_resolver::loader::MemoryFilesRc;

pub(crate) fn memory_file(url: Url, source: String) -> File {
    File {
        url: url.clone(),
        mtime: None,
        maybe_headers: None,
        source: source.into_bytes().into(),
        loaded_from: LoadedFrom::Local,
    }
}

pub(crate) fn insert_memory_file(memory_files: &MemoryFilesRc, url: Url, source: String) {
    memory_files.insert(url.clone(), memory_file(url, source));
}
