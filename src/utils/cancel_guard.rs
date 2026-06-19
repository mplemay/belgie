pub(crate) trait Cancel {
    fn cancel(&self);
}

pub(crate) struct CancelGuard<T: Cancel> {
    inner: Option<T>,
}

impl<T: Cancel> CancelGuard<T> {
    pub(crate) fn new(inner: T) -> Self {
        Self { inner: Some(inner) }
    }

    pub(crate) fn disarm(&mut self) {
        self.inner = None;
    }

    pub(crate) fn get(&self) -> &T {
        self.inner
            .as_ref()
            .expect("cancel guard should be armed while in use")
    }
}

impl<T: Cancel> Drop for CancelGuard<T> {
    fn drop(&mut self) {
        if let Some(inner) = &self.inner {
            inner.cancel();
        }
    }
}
