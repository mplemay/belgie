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

Use `Script.from_file()` for disk scripts. Use `Runtime.from_folder()` only when relative `./` imports need a project
root.

**Incorrect:**

```python
from belgie import Runtime, Script

script = Script.from_file("greet.ts")
with Runtime() as runtime:
    runtime(script)({"name": "belgie"})
```

**Correct:**

```python
from pathlib import Path
from belgie import Runtime, Script

script = Script.from_file(Path("frontend/greet.ts"))
with Runtime.from_folder("frontend") as runtime:
    runtime(script)({"name": "belgie"})
```

`Runtime.from_folder()` does not install npm or JSR packages.
