# Script Export Contract

See [references/scripts.md](../references/scripts.md) for file loading, TypeScript, and relative imports.

## Contents

- Callable default export
- Named `run` export fallback
- Non-callable exports
- File scripts vs inline scripts

---

## Callable default export

**Incorrect:**

```javascript
export default { value: 42 };
```

**Correct:**

```javascript
export default function run() {
  return 42;
}
```

```javascript
export default () => 42;
```

---

## Named `run` export fallback

Belgie accepts `export function run(...)` when there is no callable default export.

**Incorrect:**

```javascript
export function helper() {
  return 42;
}
```

**Correct:**

```javascript
export function run() {
  return 42;
}
```

---

## Non-callable exports

**Incorrect:**

```javascript
export default 42;
```

**Correct:**

```javascript
export default () => 42;
```

---

## File scripts vs inline scripts

`Script.from_file()` resolves `./` imports relative to the script file's directory. Inline `Script("...")` source
resolves `./` imports from the runtime cwd — use `Runtime.from_folder(path)` to set that root.

**Incorrect (inline script without `from_folder`):**

```python
from belgie import Runtime, Script

script = Script('import { value } from "./value.ts"; export default () => value;')
with Runtime() as run:
    run(script)()
```

**Correct (inline script — set runtime cwd):**

```python
from belgie import Runtime, Script

script = Script('import { value } from "./value.ts"; export default () => value;')
with Runtime.from_folder("frontend") as run:
    run(script)()
```

**Correct (file on disk — relatives resolve from script directory):**

```python
from pathlib import Path
from belgie import Runtime, Script

script = Script.from_file(Path("frontend/greet.ts"))
with Runtime() as run:
    run(script)({"name": "belgie"})
```

`Runtime.from_folder()` does not install npm or JSR packages.
