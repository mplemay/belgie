use pyo3::exceptions::PyException;

pyo3::create_exception!(belgie.errors, BelgieError, PyException);
pyo3::create_exception!(belgie.errors, BelgieRuntimeError, BelgieError);
pyo3::create_exception!(belgie.errors, BelgieModuleError, BelgieError);
pyo3::create_exception!(belgie.errors, BelgieJavaScriptError, BelgieError);
