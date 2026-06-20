# JSON Bridge

See [references/scripts.md](../references/scripts.md) for argument passing patterns.

## Contents

- JSON-serializable values only
- Safe integer range
- Positional args and keyword options object
- Import errors from `belgie.errors`

---

## JSON-serializable values only

**Incorrect:**

```python
from belgie import Runtime, Script

with Runtime() as runtime:
    runtime(Script("export default function run(input) { return input; }"))({"value": object()})
```

**Correct:**

```python
from belgie import Runtime, Script

with Runtime() as runtime:
    runtime(Script("export default function run(input) { return input; }"))({"value": 42})
```

Reject cycles, sets, bytes, arbitrary Python objects, NaN/Inf, ints outside JS safe integer range, and JS
BigInt/Symbol/Date/Map/Set on return.

---

## Safe integer range

Python `int` values must fit JavaScript's safe integer range (±2⁵³).

**Incorrect:**

```python
from belgie import Runtime, Script

with Runtime() as runtime:
    runtime(Script("export default function run(input) { return input; }"))({"value": 2**53})
```

**Correct:**

```python
from belgie import Runtime, Script

with Runtime() as runtime:
    runtime(Script("export default function run(input) { return input; }"))({"value": "9007199254740992"})
```

---

## Positional args and keyword options object

Positional Python args become JS positional args. Keyword args become a final `options` object.

**Incorrect:**

```javascript
export default function run(options) {
  return options;
}
```

```python
runtime(script)(first=1, second=2)
```

**Correct:**

```javascript
export default function run(first, second, options) {
  return { values: [first, second], options };
}
```

```python
runtime(script)(1, "two", z=True, a=False)
```

---

## Import errors from `belgie.errors`

**Incorrect:**

```python
from belgie import BelgieRuntimeError
```

**Correct:**

```python
from belgie.errors import BelgieRuntimeError, BelgieModuleError, BelgieJavaScriptError
```
