# Runtime Selection

See [references/architecture.md](../references/architecture.md) for the full decision guide.

## Contents

- Dependency-free inline scripts
- npm and JSR imports
- Inline relative imports
- File scripts with relative imports
- npm package binaries

---

## Dependency-free inline scripts

**Incorrect:**

```python
from belgie import Runtime, Script

script = Script('import { join } from "std_path"; export default () => join.name;')
with Runtime() as runtime:
    runtime(script)()
```

**Correct:**

```python
from belgie import Runtime, Script

with Runtime() as runtime:
    runtime(Script("export default (n) => n + 1"))(41)
```

---

## npm and JSR imports

**Incorrect:**

```python
from belgie import Runtime, Script

with Runtime() as runtime:
    runtime(Script('import react from "react"; export default () => react.version;'))()
```

**Correct:**

```python
from belgie import Environment, Runtime, Script

with Environment({"react": "^19"}) as env:
    env.install()
    with Runtime(env=env) as runtime:
        runtime(Script('import react from "react"; export default () => react.version;'))()
```

---

## Inline relative imports

Inline `Script("...")` source resolves `./` imports from the runtime cwd.

**Incorrect:**

```python
from belgie import Runtime, Script

script = Script('import { value } from "./value.ts"; export default () => value;')
with Runtime() as runtime:
    runtime(script)()
```

**Correct:**

```python
from belgie import Runtime, Script

script = Script('import { value } from "./value.ts"; export default () => value;')
with Runtime.from_folder("frontend") as runtime:
    runtime(script)()
```

---

## File scripts with relative imports

`Script.from_file(path)` resolves `./` imports relative to the script file's directory. Plain `Runtime()` is sufficient.

**Incorrect:**

```python
from belgie import Runtime, Script

script = Script('import { value } from "./value.ts"; export default () => value;')
with Runtime() as runtime:
    runtime(script)()
```

**Correct:**

```python
from pathlib import Path
from belgie import Runtime, Script

# main.ts imports from "./lib/math.ts" on disk
script = Script.from_file(Path("main.ts"))
with Runtime() as runtime:
    runtime(script)({"value": 21})
```

---

## npm package binaries

**Incorrect:**

```python
from belgie import Command, Runtime

with Runtime() as runtime:
    runtime(Command("vite"))("--version")
```

**Correct:**

```python
from belgie import Command, Environment, Runtime

with Environment({"vite": "^6"}) as env:
    env.install()
    with Runtime(env=env) as runtime:
        runtime(Command("vite"))("--version")
```

Do not put JavaScript dependencies in the Python project's `pyproject.toml`.
