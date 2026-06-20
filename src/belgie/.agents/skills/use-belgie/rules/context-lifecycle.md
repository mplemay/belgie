# Context Lifecycle

See [references/environment.md](../references/environment.md) and
[references/architecture.md](../references/architecture.md) for full lifecycle details.

## Contents

- Enter Environment and Runtime before use
- Pass an entered environment to Runtime
- Install before scripts or commands that need packages
- Nest Runtime inside an active Environment
- One active Runtime context at a time
- Call runners inside the context

---

## Enter Environment and Runtime before use

**Incorrect:**

```python
from belgie import Environment, Runtime, Script

env = Environment({"std_path": "jsr:@std/path@^1"})
env.install()
runtime = Runtime(env=env)
runtime(Script("export default () => 42;"))()
```

**Correct:**

```python
from belgie import Environment, Runtime, Script

with Environment({"std_path": "jsr:@std/path@^1"}) as env:
    env.install()
    with Runtime(env=env) as runtime:
        runtime(Script("export default () => 42;"))()
```

---

## Pass an entered environment to Runtime

`Runtime(env=...)` requires the environment to be inside its context manager first.

**Incorrect:**

```python
from belgie import Environment, Runtime, Script

env = Environment()
runtime = Runtime(env=env)
with env:
    with runtime:
        runtime(Script("export default () => 42;"))()
```

**Correct:**

```python
from belgie import Environment, Runtime, Script

env = Environment()
with env:
    with Runtime(env=env) as runtime:
        runtime(Script("export default () => 42;"))()
```

---

## Install before scripts or commands that need packages

**Incorrect:**

```python
with Environment({"std_path": "jsr:@std/path@^1"}) as env:
    with Runtime(env=env) as runtime:
        runtime(Script('import { join } from "std_path"; export default () => join.name;'))()
```

**Correct:**

```python
with Environment({"std_path": "jsr:@std/path@^1"}) as env:
    env.install()
    with Runtime(env=env) as runtime:
        runtime(Script('import { join } from "std_path"; export default () => join.name;'))()
```

---

## Nest Runtime inside an active Environment

**Incorrect:**

```python
from belgie import Command, Environment, Runtime

env = Environment({"vite": "^6"})
with Runtime(env=env) as runtime:
    with env:
        env.install()
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

---

## One active Runtime context at a time

**Incorrect:**

```python
runtime = Runtime()
with runtime:
    with runtime:
        runtime(Script("export default () => 42;"))()
```

**Correct:**

```python
with Runtime() as runtime:
    runtime(Script("export default () => 42;"))()
```

---

## Call runners inside the context

**Incorrect:**

```python
with Runtime() as runtime:
    run = runtime(Script("export default () => 42;"))

result = run()
```

**Correct:**

```python
with Runtime() as runtime:
    run = runtime(Script("export default () => 42;"))
    result = run()
```
