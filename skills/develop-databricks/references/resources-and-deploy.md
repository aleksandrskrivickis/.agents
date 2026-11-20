# Resources, post-deploy & deploy

> **Source.** `[repo]` — distilled from a production Lakeflow bundle and the deploy failures it
> hit. `[docs]` marks documented Databricks CLI/bundle behaviour; `[deduced]` an inference.

## Resource types & key uniqueness

Under `resources:` (globally in `resources/*.yml`, or inline under `targets.<t>.resources`):
`pipelines`, `jobs`, `job_runs`, `model_serving_endpoints`, `postgres_projects`,
`postgres_branches`, `postgres_synced_tables`, and more.

- **Resource keys are globally unique across ALL types** (see SKILL rule 1). The key is
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
                - glob: {include: ../src/pipeline/**}   # glob in notebook source; renumbering files is safe
            configuration:                     # Spark confs read via spark.conf.get(...) in the source
                deployed_git_commit: ${bundle.git.commit}
                pipelines.numUpdateRetryAttempts: "0"
            environment:
                dependencies:                  # RUNTIME deps go HERE, not pyproject [project].dependencies
                    - requests==2.32.4
                    - --editable ${workspace.file_path}
                    - ../dist/*.whl
```

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
> covered in [lakebase-and-data-api.md](./lakebase-and-data-api.md) — including the trap that a role
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
