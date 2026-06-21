# JSON Bridge

See [references/scripts.md](../references/scripts.md) for argument passing patterns.

## Contents

- JSON-serializable values only
- Safe integer range
- Positional args and named keyword args
- Import errors from `belgie.errors`

---

## JSON-serializable values only

**Incorrect:**

```python
from belgie import Runtime, Script

with Runtime() as run:
    run(Script("export default function run(input) { return input; }"))({"value": object()})
```

**Correct:**

```python
from belgie import Runtime, Script

with Runtime() as run:
    run(Script("export default function run(input) { return input; }"))({"value": 42})
```

Reject cycles, sets, bytes, arbitrary Python objects, NaN/Inf, ints outside JS safe integer range, and JS
BigInt/Symbol/Date/Map/Set on return.

---

## Safe integer range

Python `int` values must fit JavaScript's safe integer range (±2⁵³).

**Incorrect:**

```python
from belgie import Runtime, Script

with Runtime() as run:
    run(Script("export default function run(input) { return input; }"))({"value": 2**53})
```

**Correct:**

```python
from belgie import Runtime, Script

with Runtime() as run:
    run(Script("export default function run(input) { return input; }"))({"value": "9007199254740992"})
```

---

## Positional args and named keyword args

Belgie maps keyword args to named JavaScript parameters based on the exported `run` signature. Use a final `options`
parameter or `...options` rest parameter for overflow kwargs.

**Named parameters:**

```javascript
export default function run(first, second) {
  return { first, second };
}
```

```python
run(script)(first=1, second=2)
```

**Single input object via kwargs:**

```javascript
export default function run(input: { name: string }) {
  return input;
}
```

```python
run(script)(name="belgie")
```

**Overflow options:**

```javascript
export default function run(first, second, options) {
  return { values: [first, second], options };
}
```

```python
run(script)(1, "two", z=True, a=False)
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
