# Variables & interpolation

> **Source.** `[repo]` — distilled from a production Lakeflow bundle and the deploy failures it
> hit. `[docs]` marks documented Databricks CLI/bundle behaviour; `[deduced]` an inference.

## Declaring variables

```yaml
variables:
    catalog:
        description: The Unity Catalog catalog the pipeline writes to.
        default: my_catalog
    schema:
        description: Required; each target sets its own.      # NO default = required variable
    limit_per_source:
        description: Optional row cap, wired only into dev.
        default: 20
```

- A variable **without a `default`** is **required** — but only enforced when the **selected target
  references it**. `bundle validate -t <target-that-never-uses-it>` reaches the auth step, not a
  "required variable" error. (So unreferenced missing-required vars don't block that target.)
- Override at the CLI with `--var="limit_per_source=100"`, or per target under
  `targets.<t>.variables:`.

## Interpolation namespaces

| Form | Resolves to |
|---|---|
| `${var.<name>}` | a bundle variable |
| `${bundle.name}` / `${bundle.target}` | bundle name / selected target name |
| `${bundle.git.branch}` / `${bundle.git.commit}` | git provenance at deploy |
| `${workspace.current_user.userName}` / `.short_name` | deploying user's email / short name |
| `${workspace.file_path}` | deployed bundle file root (used by `--editable` deps) |
| `${resources.<type>.<key>.id}` | a sibling resource's id (ordering + wiring) |
| `${resources.postgres_synced_tables.<key>.status.pipeline_id}` | an autoscaling synced table's backing pipeline id |

## What you CANNOT interpolate / transforms that don't exist

- **`workspace.host` cannot take `${var.*}`.** Host is resolved during auth config *before* variables
  expand → `${var.host}` leaks literally and errors `invalid character "{" in host name` + a
  host/profile mismatch. Keep host literal, override per-target, or drive via `DATABRICKS_HOST` /
  profile.
- **No string functions.** `${bundle.target}` is verbatim substitution — no case change, no
  hyphen→underscore. Target `fiat-individual` → schema `..._fiat-individual` (hyphen is an awkward
  UC identifier); hardcode the schema for hyphenated targets instead of deriving it.
- `${workspace.current_user.short_name}` is a safe identifier source for per-user dev schemas.

## Merge semantics across target overrides (critical)

When a target repeats a resource key to override it:

- **Maps deep-merge.** A pipeline's `configuration:` (a map) merges — a per-target block need only add
  or override individual keys; global keys survive. Same for other map fields.
- **Arrays replace.** A job's `tasks:` list (an array) is **replaced**, not merged. If a target
  overrides a job, **restate the entire `tasks:` list**, or the omitted tasks vanish.

```yaml
# global resources/jobs.yml
resources:
  jobs:
    my-workflow:
      tasks: [ {task_key: a, ...}, {task_key: b, ...} ]

targets:
  prod:
    resources:
      jobs:
        my-workflow:
          tasks: [ {task_key: a, ...}, {task_key: b, ...} ]   # FULL list, not just the changed task
```

## Reading resolved values

`bundle validate -o json` prints the **pre-substitution** config: `${var.*}` appear **unexpanded**
for every resource. That is NOT evidence a resource ignores a variable — interpolation happens at
deploy. See the real values in the deploy API request or the resulting UC/permission error, not in
`-o json`.
