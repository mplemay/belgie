# Runtime Selection

See [references/architecture.md](../references/architecture.md) for the full decision guide.

## Contents

- Dependency-free inline scripts
- npm, JSR, and URL imports
- Inline relative imports
- File scripts with relative imports
- npm package binaries

---

## Dependency-free inline scripts

**Incorrect:**

```python
from belgie import Runtime, Script

script = Script('import { join } from "std_path"; export default () => join.name;')
with Runtime() as run:
    run(script)()
```

**Correct:**

```python
from belgie import Runtime, Script

with Runtime() as run:
    run(Script("export default (n) => n + 1"))(41)
```

---

## npm, JSR, and URL imports

**Incorrect:**

```python
from belgie import Runtime, Script

script = Script('import react from "react"; export default () => react.version;')

with Runtime() as run:
    run(script)()
```

**Correct:**

```python
from belgie import Runtime, Script

script = Script('import react from "npm:react@^19"; export default () => react.version;')

with Runtime() as run:
    run(script)()
```

Use `Environment` when you need dependency aliases, local `file:` packages, frozen lockfiles, custom cache/options, or
commands.

---

## Inline relative imports

Inline `Script("...")` source resolves `./` imports from the runtime cwd.

**Incorrect:**

```python
from belgie import Runtime, Script

script = Script('import { value } from "./value.ts"; export default () => value;')
with Runtime() as run:
    run(script)()
```

**Correct:**

```python
from belgie import Runtime, Script

script = Script('import { value } from "./value.ts"; export default () => value;')
with Runtime.from_folder("frontend") as run:
    run(script)()
```

---

## File scripts with relative imports

`Script.from_file(path)` resolves `./` imports relative to the script file's directory. Plain `Runtime()` is sufficient.

**Incorrect:**

```python
from belgie import Runtime, Script

script = Script('import { value } from "./value.ts"; export default () => value;')
with Runtime() as run:
    run(script)()
```

**Correct:**

```python
from pathlib import Path
from belgie import Runtime, Script

# main.ts imports from "./lib/math.ts" on disk
script = Script.from_file(Path("main.ts"))
with Runtime() as run:
    run(script)({"value": 21})
```

---

## npm package binaries

**Incorrect:**

```python
from belgie import Command, Runtime

with Runtime() as run:
    run(Command("vite"))("--version")
```

**Correct:**

```python
from belgie import Command, Environment, Runtime

with Environment({"vite": "^6"}) as env:
    env.install()
    with Runtime(env=env) as run:
        run(Command("vite"))("--version")
```

Do not put JavaScript dependencies in the Python project's `pyproject.toml`.
