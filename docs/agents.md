# Documentation Guidelines

Agent instructions for authoring Belgie's published docs. This file is excluded from
the docs site (`exclude_docs` in `mkdocs.yml`) and must never appear in `nav`.

**When to check:** writing or updating anything under `docs/`, adding pages to
`mkdocs.yml`, or changing user-facing behavior that needs documentation.

## Stack

Docs are built with **MkDocs** and **Material for MkDocs**. Config lives in
`mkdocs.yml` at the repo root. Content lives under `docs/`.

- Prefer features already enabled in `mkdocs.yml`: admonitions, tabbed content,
  code copy/annotate/select, mermaid, snippets, search.
- Do not add plugins, theme overrides, or linter/formatter config changes without
  explicit permission.
- Verify with `uv sync --group docs --no-install-project` then
  `uv run --no-project mkdocs build --strict` (and
  `uv run --no-project mkdocs serve` when checking links locally) before
  considering docs done.

## Information architecture

Register every public page in `mkdocs.yml` `nav`. Orphan files under `docs/` that
are meant for the site must be linked from nav. Keep this file excluded.

Recommended top-level shape:

```yaml
nav:
  - Home: index.md
  - Install: install.md
  - Core Concepts:
      - Runtime: runtime.md
      - Script: script.md
      - Environment: environment.md
      - Command: command.md
  - MCP Apps: mcp-apps.md
  - AI Agents:
      - Overview: agents/overview.md
      - Pydantic AI: agents/pydantic-ai.md
      - LangChain: agents/langchain.md
  - CLI: cli.md
  - Packages:
      - "@belgie/mcp": packages/mcp.md
      - "@belgie/render": packages/render.md
  - Examples:
      - examples/index.md
      # one page per example or themed group, pulling from examples/
  - Help: help.md
  - Troubleshooting: troubleshooting.md
  - Project:
      - Contributing: contributing.md
      - Changelog: changelog.md
```

Adapt labels and paths as the product grows, but keep the same roles:

| Section | Purpose |
| --- | --- |
| Home | Product pitch, hello-world, next steps |
| Install | Default install, extras, optional skill install |
| Core Concepts | `Runtime`, `Script`, `Environment`, `Command` |
| MCP Apps | `BelgieExtension`, widgets, Vite, `[tool.belgie.dependencies]` |
| AI Agents | Shared `run_code` session; integration-specific pages |
| CLI | `add`, `lock`, `install`, `update`, `list`, `run` |
| Packages | User-facing JS packages when they need dedicated docs |
| Examples | Walkthroughs that pull from `examples/` |
| Help / Troubleshooting | Support channels; FAQ by error or symptom |
| Project | Contributing, changelog / upgrade notes |

**Placement rules:**

- Keep core concept pages **integration-agnostic**: one minimal example plus links
  to MCP Apps / AI Agents pages for integration-specific detail.
- Put extras, env vars, and provider- or framework-specific config on the
  integration page that owns them.
- One canonical page per topic. Link to it instead of duplicating lists or
  summaries maintained elsewhere.
- Prefer nesting related subtopics under a parent section in nav and on the page
  rather than scattering many top-level files.

## Progressive disclosure

Structure each feature area so readers build a mental model in order:

1. Concept (what it is and when to use it)
2. Capabilities (what you can do with it)
3. Examples (standalone / complete first)
4. Configuration (defaults and when to override)
5. Edge cases and limitations

Show the **recommended approach first**, then introduce alternatives with explicit
relational language ("In addition to...", "As an alternative to...") and name the
specific features. Explain trade-offs (limitations, requirements, benefits,
use cases) and warn when combining alternatives conflicts.

## Page templates

### Home / overview

1. Purpose-first lead (what Belgie is for)
2. Short "why use this" list with deep links into concepts
3. Install one-liner
4. Minimal complete example
5. One richer path (e.g. MCP Apps or agents)
6. Next steps

### Install

1. Default install first (`uv add belgie`)
2. Optional extras with deep links to the pages that need them (`mcp`, `cli`,
   `pydantic-ai`, `langchain`)
3. Optional skill / tooling install when relevant
4. Keep slim or advanced install notes after the happy path

### Concept page

1. H1 + purpose-first lead (what it is / when to reach for it)
2. Short intro; compare to related concepts with links when helpful
3. Recommended approach
4. Titled, complete example (context → code → caveats)
5. Variants, configuration, defaults
6. Edge cases
7. See also

### Integration page (MCP Apps, Pydantic AI, LangChain, packages)

1. Purpose-first lead
2. Install / extras
3. Configuration (env, project config, options)
4. Usage with a minimal complete example
5. Composition constraints and safety notes
6. See also (core concepts + examples)

### Example walkthrough

1. One or two sentence pitch
2. "Demonstrates:" bullet list linking to concept pages
3. Running the example (commands, env, working directory)
4. Example code pulled from `examples/` when the file is non-trivial
5. Notes / extensions

### Troubleshooting

- Organize by **error string or symptom as the heading**
- Short cause + fix
- Cross-link to the concept or install page that prevents the issue

### Help

- Keep minimal: where to ask questions and how to file issues
- Link troubleshooting rather than duplicating it

### Changelog / upgrade guide

- Prefer an upgrade narrative (breaking changes by version, migration steps)
  over a raw dump of every commit
- Point primary docs at current APIs only; put historical paths here

## API documentation

Root agent instructions discourage module docstrings, and the docs stack does not
use autodoc generators. Document public APIs in **hand-written** concept and
integration guides:

- Prefer realistic examples and concise parameter / option tables over signature
  dumps
- Focus on what users control: public constructors, options, return shapes,
  defaults, and failure modes
- Hide implementation details (`belgie._core`, private helpers) unless they change
  a user decision
- When a public symbol appears in prose, wrap it in backticks and link to its
  canonical concept section when one exists

## Writing style

- Factual and task-oriented. No marketing hype ("blazingly fast", "battle-tested")
  or editorializing adjectives.
- Avoid absolute claims ("never", "always", "guaranteed") unless they are literally
  true and load-bearing. Name the mechanism instead.
- Second person ("you"); imperative for how-tos.
- Product name is **Belgie** (one word). Be consistent in headings, nav, and prose.
- No em-dashes (`—`). Use `--` for an aside, or split into two sentences. Prefer
  plain ASCII punctuation over decorative Unicode.
- Bold sparingly: lead-in terms in lists, not whole sentences.
- Use Markdown heading syntax (`##`, `###`) for sections -- never bold text as a
  fake heading.
- Purpose-first openings: state what the page is for and when to use it. Do not
  lead with internal hook names, private APIs, or implementation trivia.
- Document what the code does now, not what it used to do. Skip "legacy" /
  "originally" history in user docs unless it is an upgrade guide.
- Consistent terminology across code, docs, CLI help, and errors (same spelling
  and casing for public names).
- Omit deprecated approaches from primary docs. Document only current patterns;
  link an upgrade note when users may still be on the old path.
- Do not document features "working as expected." Focus on integration concerns,
  limitations, defaults, and deviations users must know.
- Document default behavior and when to override it for configurable features.

## Look and callouts

Use Material / MkDocs conventions already enabled in this repo:

- **Admonitions** for callouts -- not blockquotes or GitHub alerts:

  ```markdown
  !!! note "Import path"
      Import from `belgie.mcp`, not internal modules.

  !!! tip
      Prefer `Environment` when you need a reusable sandbox.

  !!! warning "Not a security boundary"
      ...
  ```

- Prefer `note`, `tip`, `warning`, and `info`. Use stronger types only when the
  risk is real.
- **Tables** for comparisons, extras matrices, CLI command catalogs, and option
  summaries.
- **Tabs** (`=== "uv"`) when showing alternative install or run commands. Prefer
  `uv` as the primary path; show `pip` only when useful.
- **Mermaid** for architecture or flow diagrams when a short diagram beats a long
  paragraph.
- Code annotations (`# (1)!` with numbered notes below the fence) for non-obvious
  lines in longer examples.
- Keep visual chrome minimal: no badge clusters, marketing sticker callouts, or
  decorative card layouts in Markdown content.

## Cross-linking

- Link concepts, features, and sections with relative paths and anchors:
  `[Runtime](runtime.md)`, `[extras](install.md#extras)`.
- Establish one canonical page per topic and link to it.
- Link official third-party docs for external setup (API keys, framework
  install) instead of duplicating those lists.
- Title overrides in nav use `Label: path.md` when the filename should not be the
  display name.
- Explicit heading anchors when a stable link target matters:
  `## Registering widgets {#registering-widgets}`.

## Code examples

Structure every example as: **context / intro → code block → caveats / details**.
Never put a code block before the reader knows what it is for.

Rules:

- Prefer complete, copy-pasteable snippets with real imports and current public
  APIs.
- Demonstrate realistic use cases that show *why* the feature matters. Avoid toy
  snippets that obscure the value, and avoid debugging scaffolding as the main
  example.
- Use fence titles for named examples:

  ````markdown
  ```python {title="hello.py"}
  from belgie import Runtime
  ...
  ```
  ````

- Chain follow-on examples with `requires="hello.py"` when a later block depends
  on an earlier one.
- Prefer examples that can be executed or statically checked. Use fence-level
  `{test="skip"}` or `{lint="skip"}` only when unavoidable (external services,
  credentials, non-deterministic behavior). Do not litter examples with inline
  `# noqa` or `# type: ignore`.
- Consolidate parameter variations into one annotated block. Split only for
  mutually exclusive options or distinct use cases.
- Prefer `uv` in install and run instructions. Example:

  ```bash
  uv add belgie
  uv add "belgie[mcp,cli]"
  ```

- Pull non-trivial examples from `examples/` via snippets rather than duplicating
  large files in Markdown.
- Keep examples aligned with shipped sample projects under `examples/basic/`,
  `examples/ui/`, and `examples/ai/`.
- Use actual, currently available package and model names. Do not invent APIs.

## What to include

Every mature docs set for this project should cover:

- Install and extras
- A path from zero to a working Runtime / Script example
- Core sandbox concepts
- MCP Apps (widgets + Python tools)
- AI agent integrations (`run_code` via supported frameworks)
- CLI for dependency and project workflows
- At least one example walkthrough per major path (basic, UI, agents)
- Troubleshooting for common setup and runtime failures
- Project pages (contributing, changelog) when the site is public-facing

## What not to include

- This file (`docs/agents.md`) or other agent-only instructions
- Deprecated APIs as the primary teaching path
- Internal modules and implementation walkthroughs that do not affect user
  choices
- Duplicated third-party setup that belongs on an upstream docs site
- Marketing copy, absolute slogans, or filler that restates the signature
- Autogenerated API trees (unless the project later adopts docstrings + an autodoc
  plugin with explicit approval)

## Maintenance

- When user-facing behavior, public APIs, CLI flags, extras, or defaults change,
  update the relevant docs in the **same change**.
- Register new public pages in `mkdocs.yml` `nav`.
- Cross-reference overlapping features and explain trade-offs.
- Keep README examples and docs examples consistent when they teach the same
  path; prefer linking rather than maintaining three divergent copies.
- Before finishing docs work: `uv sync --group docs --no-install-project` then
  `uv run --no-project mkdocs build --strict`.
- Never add `docs/agents.md` to `nav` or remove it from `exclude_docs`.
