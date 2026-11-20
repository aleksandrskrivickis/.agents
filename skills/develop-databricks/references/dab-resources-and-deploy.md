# Resources, post-deploy & deploy

> **Source.** `[repo]` — distilled from a production Lakeflow bundle and the deploy failures it
> hit. `[docs]` marks documented Databricks CLI/bundle behaviour; `[deduced]` an inference.

## Shape of a bundle

```
my-bundle/
├── databricks.yml                 # bundle name, uuid, targets (dev/prod), variables, artifacts
├── resources/
│   ├── sample_job.job.yml         # a job definition
│   └── bundle_etl.pipeline.yml    # a pipeline definition
├── src/                           # the Python the job and pipeline run
└── tests/                         # pytest, with a conftest fixture
```

The root `databricks.yml` it all hangs off, with the three traps visible in one place — a top-level
`include:`, a literal `workspace.host`, and a variable with no default:

```yaml
bundle:
    name: my-bundle
    uuid: <stable-uuid>

include:
    - resources/*.yml                 # top-level ONLY — there is no per-target include

artifacts:
    python_artifact:
        type: whl
        build: uv build --wheel
        dynamic_version: true

variables:
    catalog: {default: my_catalog}
    schema:  {description: "Required; each target sets its own."}   # no default = required

workspace:
    host: https://<workspace>.azuredatabricks.net    # literal — NOT ${var.*}-interpolatable

targets:
    dev:
        default: true
        mode: development                             # [dev <user>] prefix + paused schedules
        workspace:
            root_path: /Workspace/Assets/Bundles/Individual/${workspace.current_user.short_name}/${bundle.name}/${bundle.target}
        variables:
            schema: ${workspace.current_user.short_name}_dev
    prod:
        mode: production
        variables:
            schema: my_schema_prod
```

Bundles need Databricks CLI **v0.218.0+**; `job_runs` needs **v1.7.0+** and the direct deployment
engine. You can also create and deploy a bundle entirely in the workspace UI without installing the
CLI. For auth, OAuth U2M (`databricks auth login`) is the recommended path.

## Resource types & key uniqueness

Under `resources:` (globally in `resources/*.yml`, or inline under `targets.<t>.resources`):
`pipelines`, `jobs`, `job_runs`, `model_serving_endpoints`, `postgres_projects`,
`postgres_branches`, `postgres_synced_tables`, and more.

- **Resource keys are globally unique across ALL types** (see the deployment rules in [the skill overview](../SKILL.md)). The key is
  bundle-internal; the deployed identity is the resource's own `name` / `id` / `project_id` field, so
  the key can be renamed without changing the deployed object.

## Pipelines: `configuration`, `event_log`, `environment`

```yaml
resources:
    pipelines:
        my-pipeline:
            name: my-pipeline-${bundle.target}
            catalog: ${var.catalog}
            schema: ${var.schema}
            serverless: true
            event_log:                         # publish the pipeline event log as a queryable table
                catalog: ${var.catalog}
                schema: ${var.schema}
                name: event_log
            libraries:
                - glob: {include: ../src/pipeline/**}   # include ONLY — there is no `exclude` key
            configuration:                     # Spark confs read via spark.conf.get(...) in the source
                deployed_git_commit: ${bundle.git.commit}
                pipelines.numUpdateRetryAttempts: "0"
            environment:
                dependencies:                  # RUNTIME deps go HERE, not pyproject [project].dependencies
                    - requests==2.32.4
                    - --editable ${workspace.file_path}
                    - ../dist/*.whl
```

- **`glob` takes `include` and nothing else — there is no paired `exclude`.** That shapes the source
  tree rather than the config: narrow the include (`transformations/**/*.py` over
  `transformations/**`), use several specific includes instead of one broad one, move helpers and
  work-in-progress into a folder no include matches, or list files explicitly when the set you want
  is small. Glob negation is not standardised here the way `.gitignore` negation is. Renumbering
  files inside a matched folder is still safe. `[?]`
- **Runtime Python deps belong in `environment.dependencies`**, not `[project].dependencies` — the
  latter is cached during development and won't pick up changes. Mirror them into a dev dependency
  group only where local tests need them.
- `configuration` values are strings read by the pipeline via `spark.conf.get(...)`; adding a key
  usually means touching three places — the bundle `variable`, the pipeline `configuration`, and the
  notebook that reads it.
- `pipelines.numUpdateRetryAttempts: "0"` in `configuration` stops the runtime relaunching a failed
  update (default is 5 for triggered pipelines) — a *job* task `max_retries: 0` does **not** cover it.

## Jobs, `job_runs` (post-deploy run-once), and ordering

```yaml
resources:
    jobs:
        bootstrap:
            name: my-bundle-${bundle.target}-bootstrap
            tasks:
                - task_key: pipeline
                  pipeline_task: {pipeline_id: ${resources.pipelines.my-pipeline.id}}
                - task_key: sync
                  depends_on: [{task_key: pipeline}]
                  pipeline_task: {pipeline_id: ${resources.postgres_synced_tables.anchor.status.pipeline_id}}
                - task_key: grant
                  depends_on: [{task_key: sync}]
                  notebook_task: {notebook_path: ./src/templates/grant.py}
    job_runs:
        post-deploy:                            # fires once on each `bundle deploy`
            job_id: ${resources.jobs.bootstrap.id}
```

- **`job_runs`** is the native "run once after deploy" mechanism — requires **Databricks CLI ≥ 1.7.0
  and the direct deployment engine**. `scripts` are manual only (`bundle run <script>`), not
  auto-on-deploy.
- **`job_runs` CANNOT depend on each other** (no ordering between them). To enforce an order
  (e.g. scrape → sync → grant) put the steps as **tasks in ONE job** with `depends_on`, and trigger
  that single job from one `job_runs`.
- A notebook task with **no cluster** runs on **serverless** (a common repo convention).

## Lakebase / Postgres synced tables (bin-packing)

> The project and branch these tables live in, and the **Data API** that serves them over HTTP, are
> covered in [dab-lakebase.md](./dab-lakebase.md) — including the trap that a role
> created via `postgres_roles` cannot be granted to `authenticator`.

```yaml
resources:
    postgres_synced_tables:
        anchor:                                 # owns the sync pipeline
            synced_table_id: ${var.catalog}.${var.schema}.synced_x   # LITERAL 3-part name
            source_table_full_name: ${var.catalog}.${var.schema}.x
            branch: projects/${bundle.name}/branches/dev
            postgres_database: ${var.catalog}
            scheduling_policy: SNAPSHOT
            create_database_objects_if_missing: true
            primary_key_columns: [id]
            new_pipeline_spec: {storage_catalog: ${var.catalog}, storage_schema: ${var.schema}}
        follower:
            # ...same shape...
            scheduling_policy: SNAPSHOT         # MUST match the anchor to bin-pack
            existing_pipeline_id: ${resources.postgres_synced_tables.anchor.status.pipeline_id}
```

- The backing pipeline id of an **autoscaling** synced table is
  `${resources.postgres_synced_tables.<key>.status.pipeline_id}` — **not**
  `...data_synchronization_status.pipeline_id` (that path is the older *provisioned*
  `synced_database_table` and fails deploy: "field data_synchronization_status not found").
- **Bin-pack** multiple synced tables into one pipeline: the anchor carries `new_pipeline_spec`, the
  others carry `existing_pipeline_id` pointing at the anchor's `status.pipeline_id`; all must share
  the same `scheduling_policy`.
- `synced_table_id` is taken **literally** as a 3-part name — point `catalog` at a **real** catalog
  (a placeholder like `default` → `CATALOG_DOES_NOT_EXIST`). There is no fallback to the workspace
  default-catalog setting.
- A synced table's `scheduling_policy` / column types can't change in place — **drop + recreate** to
  change them (e.g. `SNAPSHOT` is required when the source is a materialized view, because
  TRIGGERED/CONTINUOUS read via Change Data Feed which an MV doesn't support without external
  metadata).
- Cross-deploy ordering: a synced table references its Lakebase branch by a **literal path**
  (`projects/<name>/branches/<b>`), not a resource ref, so the bundle won't enforce order — deploy
  the target that creates the Lakebase project/branches **before** the one that syncs into them.

## Artifacts (the wheel)

```yaml
artifacts:
    python_artifact:
        type: whl
        build: uv build --wheel
        dynamic_version: true
```

The bundle builds the wheel on deploy; reference it from `environment.dependencies` as `../dist/*.whl`
alongside `--editable ${workspace.file_path}`.

### `dynamic_version` exists because serverless caches your stale code

This is the line worth understanding rather than copying. **Serverless keys its cached virtual
environment off the dependency set.** If the wheel ships as `mypkg-0.0.1` on every deploy, the
version string never changes, the cache never invalidates, and serverless keeps running yesterday's
code — after a `bundle deploy` that reported success. That is the whole "why is it still pointing at
the old version" class of bug, and nothing in the deploy output hints at it.

`dynamic_version: true` patches the wheel's version from the `.whl` file's timestamp on each
deploy, which breaks the cache. Four things attach to it:

- **Only valid for `type: whl`**, and only for **local wheels uploaded as part of
  `bundle deploy`** — the CLI has to be able to patch the file before upload. A wheel already
  sitting in a UC volume, or pulled from a private index, never gets patched and the problem
  returns. `[docs]`
- Needs Databricks CLI **0.245.0+**. The `artifacts_dynamic_version` **preset** (CLI 0.256.0+)
  turns it on for every artifact in the bundle; the default-python template enables it on the dev
  target automatically.
- **Scope it to dev and staging.** Production usually wants a real, traceable semver tied to a
  release, not a timestamp — so prefer the per-artifact flag or a per-target preset over switching
  it on everywhere.
- **The one-line verification:** after a deploy, look at the uploaded wheel's filename in the
  artifact path. The version suffix must change between deploys. Identical across deploys means the
  wheel is not being built locally and the patch step is being skipped silently.

### Where dependencies are pinned — three surfaces, three syntaxes

There is no single versioning mechanism in a bundle, and the three surfaces behave differently
enough that "which one am I on" is the first question:

| Surface | Where | Applies to |
|---|---|---|
| `requirements*.txt` | project root | **Local development only.** Under the jobs-as-code template `uv` resolves these into `uv.lock`, which is the local reproducibility anchor — not the deployed one |
| `libraries:` on a task | the job resource | **Classic compute.** Takes `pypi: {package: "shared-dq==0.3.1", repo: <index-url>}` for a private index, or `whl:` for a path |
| `environments[].spec.dependencies` | the job or pipeline resource | **Serverless.** Pip-style requirement strings, or a wheel glob |

Three traps across them:

- **The DBFS root is dead for wheels** — storing library files there is deprecated and disabled by
  default from DBR **15.1**. Wheels live in UC volumes or workspace files. `[docs]`
- **`environment_version` is the serverless base image, not your package version** (`1`/`2`/`3`,
  `4-scala-preview`). And it **cannot be applied through bundle YAML to a `notebook_task`** — a
  known limitation that forces you into the notebook UI. It works for `spark_python_task` and
  `python_wheel_task`. `[docs]`
- **Nothing here locks transitive dependencies at deploy time.** `bundle deploy` ships config;
  resolution happens at install on the cluster or serverless environment. `==` on your direct deps
  still lets their transitives float. If you need real determinism, ship a self-contained built
  wheel — or write down that you have accepted the float.

## Deploy / validate / run

```bash
databricks bundle validate -t <target>
databricks bundle deploy   -t <target>          # dev is default
databricks bundle run <job-or-pipeline-key> -t <target>
```

- `validate` catches **duplicate-key / schema / required-var** errors **locally, before auth** —
  hitting an auth error means structural validation already passed. (Reference-path mismatches like a
  wrong `.status.*` attribute only surface at `deploy` plan time, not `validate`.)
- Keep automated **bundle tests read-only** — `validate` only, never a real deploy, even behind a
  flag. Never deploy to shared/prod targets without explicit instruction.
