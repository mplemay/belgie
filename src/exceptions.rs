use pyo3::exceptions::PyException;

pyo3::create_exception!(_core, BelgieError, PyException);
pyo3::create_exception!(_core, BelgieRuntimeError, BelgieError);
pyo3::create_exception!(_core, BelgieModuleError, BelgieError);
pyo3::create_exception!(_core, BelgieJavaScriptError, BelgieError);
