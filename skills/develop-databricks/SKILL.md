---
name: develop-databricks
description: 'Use for any Databricks work — pipelines, deployment, or the platform itself. Pipelines: Spark Declarative Pipelines (`pyspark.pipelines` / `dp`) and the Lakeflow extensions — `@dp.table`, `create_streaming_table`, `append_flow`, expectations, AUTO CDC, streaming table vs materialized view, publishing modes and the LIVE schema, the event log, full vs selective refresh, `ignoreChanges` vs `skipChangeCommits`, the Pipelines Editor. Deployment: asset bundles (`databricks.yml`, `resources/*.yml`, `databricks bundle validate/deploy/run`) — targets and dev-vs-prod modes, variables and `${var}` interpolation, resource types, `job_runs` post-deploy, Lakebase projects/branches/synced tables and the Data API. Platform: Unity Catalog introspection via `system.information_schema`, `SYNC` from the Hive metastore, the `CREATE TABLE IF NOT EXISTS` copy-vs-refresh trap, Delta time travel, grants, secret scopes, external sources, model serving, LLM calls. Defers transform internals and Azure provisioning to related skills.'
---

# Databricks

> **What this is.** One chapter for the whole Databricks surface, in three layers:
>
> - **The pipeline** — **SDP** is the open-source declarative pipeline framework in Apache Spark
>   (`pyspark.pipelines`, since Spark 4.1); **Databricks Lakeflow pipelines** is a proprietary
>   superset that adds expectations, AUTO CDC, extra sinks, the event log and the Pipelines Editor.
>   Which half a feature belongs to decides whether your code runs anywhere else, so the two are
>   flagged throughout.
> - **The deployment** — a **bundle** is the infrastructure-as-code project around it: a root
>   `databricks.yml` plus `resources/*.yml`, applied with `databricks bundle deploy`, parameterised
>   per target (dev / staging / prod).
> - **The platform** — the work you do *beside* a pipeline: reading Unity Catalog's own metadata,
>   moving and versioning tables, clusters, secrets, external sources, model serving and Lakebase.
>
> Distilled from production Databricks projects and the failures they hit; every example uses
> invented catalog and table names. It does **not** cover what goes wrong *inside* a transform (see
> [develop-pyspark](../develop-pyspark/SKILL.md)), provisioning the Azure platform underneath (see
> [develop-infrastructure](../develop-infrastructure/SKILL.md)), or testing (see
> [test-python](../test-python/SKILL.md)).

## Detailed references

**Writing a pipeline**

- [sdp-python-api.md](./references/sdp-python-api.md) — the `dp` decorators and functions, the
  DLT→SDP mapping, and the coding rules the framework enforces.
- [sdp-expectations-policy.md](./references/sdp-expectations-policy.md) — `expect_all` vs
  `_or_drop` vs `_or_fail` and what each decides, the presence/value two-block structure, and the
  four anti-patterns an audit found in 21 real expectation blocks.
- [sdp-event-log-and-observability.md](./references/sdp-event-log-and-observability.md) — the
  event log's schema, the aggregation rules that stop you over-counting failures, publishing vs
  the TVF, where `print()` actually goes on serverless, and the row-provenance vs run-execution
  boundary.
- [sdp-operations-and-refresh.md](./references/sdp-operations-and-refresh.md) — full refresh vs
  selective full refresh vs a new flow generation, retry and cluster-shutdown settings,
  `ignoreChanges` vs `skipChangeCommits`, table layout, and a four-check triage playbook.
- [sdp-auto-cdc.md](./references/sdp-auto-cdc.md) — AUTO CDC / AUTO CDC FROM SNAPSHOT
  (Databricks-only; replaces APPLY CHANGES).
- [sdp-pipelines-editor-and-publishing.md](./references/sdp-pipelines-editor-and-publishing.md) —
  the Lakeflow Pipelines Editor, publishing modes, and where the bundle layer sits.
- [sdp-custom-data-sources.md](./references/sdp-custom-data-sources.md) — a custom
  `DataSourceStreamReader` for one offset cursor per key, why it beats an offsets table, the
  reader-only limit inside SDP, and the hole a success-filtered high-water mark leaves.
- [sdp-vs-databricks-and-naming.md](./references/sdp-vs-databricks-and-naming.md) — the
  Apache-vs-Databricks feature split, the DLT/DAB/APPLY CHANGES renames, reading an older
  codebase, and pyright stubs for the runtime API.

**Deploying a bundle**

- [dab-targets-and-modes.md](./references/dab-targets-and-modes.md) — targets, `mode: development`
  vs `production`, name prefixing and `normalizePrefix`, presets, per-target overrides, `include`
  scoping, the per-user-sandbox trap, and an admin-only target for shared infrastructure.
- [dab-variables-and-interpolation.md](./references/dab-variables-and-interpolation.md) —
  `variables:`, required vars, the `${var.*}` / `${bundle.*}` / `${workspace.*}` /
  `${resources.*.status.*}` namespaces, what can't be interpolated, map deep-merge vs array
  replace.
- [dab-resources-and-deploy.md](./references/dab-resources-and-deploy.md) — the directory shape
  and the root `databricks.yml` skeleton, resource types and key uniqueness, pipeline
  `configuration` / `environment`, `job_runs` post-deploy, synced-table bin-packing, the wheel
  artifact, and the deploy/validate/run commands.
- [dab-lakebase.md](./references/dab-lakebase.md) — `postgres_projects` and `postgres_branches`
  field by field, the PostgREST-style Data API, the role/`authenticator` grant trap, the SDK raw
  API client, and where the declarative surface stops and a script takes over.

**Unity Catalog and tables**

- [uc-introspection.md](./references/uc-introspection.md) — the two information schemas,
  privilege-aware filtering, the view catalog, the performance notes, and worked inventory
  queries.
- [uc-table-migration-and-lifecycle.md](./references/uc-table-migration-and-lifecycle.md) — `SYNC`
  in depth (external vs managed, status codes, the non-ASCII comment trap), `DEEP` vs
  `SHALLOW CLONE`, and time-travel retention with the `RESTORE` streaming caveat.
- [uc-catalog-administration.md](./references/uc-catalog-administration.md) — create a catalog on
  a managed location and grant, snapshot a schema, bulk-migrate a Hive schema.
- [uc-test-queries.md](./references/uc-test-queries.md) — time travel, a combined catalog
  inventory query, and a destructive privilege probe.
- [uc-monitoring-and-profiling.md](./references/uc-monitoring-and-profiling.md) — Lakehouse
  Monitoring / data profiling on the tables a pipeline publishes: why it attaches to the table and
  not the pipeline, the MV and 4 TB limits, and how it divides work with expectations.

**Connecting, computing and serving**

- [integration-external-sources.md](./references/integration-external-sources.md) — Neo4j, Azure
  SQL (service principal), Cosmos DB merged into Delta, and legacy ADLS/Blob mounts.
- [administration-file-operations.md](./references/administration-file-operations.md) — copy files
  with shell, copy a notebook with the Workspace export/import API.
- [administration-cluster-configuration.md](./references/administration-cluster-configuration.md)
  — enable Databricks Container Services, inject a secret as a Spark config or environment
  variable.
- [administration-credential-management.md](./references/administration-credential-management.md)
  — secret scopes, put/get/ACL, redaction, Key Vault-backed scopes.
- [mlflow-model-serving.md](./references/mlflow-model-serving.md) — log a custom MLflow `pyfunc`
  with a typed signature, register it, call the serving endpoint.
- [analysis-llm.md](./references/analysis-llm.md) — call Azure OpenAI with LangChain from secrets,
  count tokens, drive a structured prompt.

## The copy-versus-refresh trap

`CREATE TABLE IF NOT EXISTS <t> AS SELECT …` is **not** a refresh. If the target already exists, the
statement is a no-op: the `SELECT` never runs and the data never updates. A nightly job built this
way looks healthy and serves stale data forever. Choose the statement that matches your intent:

- **Create once, never overwrite** → `CREATE TABLE IF NOT EXISTS … AS SELECT …`.
- **Replace the whole table each run** → `CREATE OR REPLACE TABLE … AS SELECT …`.
- **Upsert rows** → `MERGE INTO … USING … ON … WHEN MATCHED … WHEN NOT MATCHED …`.

## The rules that prevent most failures

### Writing a pipeline

1. **A dataset function must return a DataFrame and contain only defining logic.** SDP evaluates it
   multiple times during planning, so **never** call `collect()`, `count()`, `toPandas()`, `save()`,
   `saveAsTable()`, `start()`, `toTable()` or `pivot()` inside dataset code.
2. **Streaming table ⇔ streaming read.** A streaming table needs `spark.readStream`; a materialized
   view needs a batch read. Mismatching them is the most common first error.
3. **`spark.conf.get` and `dbutils` work only on the driver.** Read config and secrets at **module
   scope** and close over them in UDFs. Pass secret scope/key *names* as configuration and resolve
   them in the source file — don't rely on `{{secrets/…}}` substitution.
4. **Choose an expectations policy deliberately.** Bare `expect_all` is advisory: violating rows are
   written exactly like valid ones and no column carries the verdict. A defensible choice, but it is
   usually reached by default rather than decided, and it means no quality rule can stop anything.
5. **The event log is the observability mechanism, not your logs.** On serverless there is no Spark
   UI and no Spark logs, and executor `print`/`logger` output has **no documented route** anywhere.
   Row-scoped provenance goes in a column; run-scoped execution is already in the event log.
6. **Don't write a `pipeline_logs` table.** It duplicates `flow_progress` and then drifts from it,
   ties log durability to the flow that writes it, and has no `update_id` to join on.
7. **A full refresh resets your position, not the world's history.** Against a source that only
   moves forward — a resume offset, a cursor-paginated API, an append-only feed — it re-reads the
   source *as it is today*, and cannot recover what the source no longer offers.
8. **Prefer a new flow generation to a truncating full refresh.** Each `append_flow` owns a
   checkpoint keyed by its **name**, so naming the flow after the thing that changed (the model, a
   config digest) appends a new generation beside the old rows — prior results stay comparable.
9. **`ignoreChanges` against a full-recompute upstream re-emits everything, every run.** Use
   `skipChangeCommits` for an append-only logical source whose files get rewritten, and never paper
   over the duplication with an unwatermarked `dropDuplicates` — that grows state without bound.
10. **Let Spark errors surface.** Broad `try`/`except` around transformations masks real errors from
    the event log. Where you must catch an `AnalysisException`, match the specific condition and
    re-raise everything else.
11. **Set retry behaviour in every target, not just `dev`.** With `pipelines.maxFlowRetryAttempts`
    and `pipelines.numUpdateRetryAttempts` set only in development, nobody can state how many times
    a production flow retries before failing.
12. **A flow cannot read its own target, and renaming does not help.** The graph is built from the
    DataFrame lineage of what the function *returns*, so a qualified `spark.table("x")` joined into
    the returned frame is still an edge — `LIVE.` versus a published name is irrelevant. Reach for
    AUTO CDC, a stateful operator, or a table the pipeline does not own.
13. **There is no pipeline-level rollback.** Each flow commits independently, so there is no
    consistent cut to return to, and `RESTORE` on a streaming table leaves the checkpoint ahead of
    the data — a permanent hole. A `DEEP CLONE` taken *before* a deploy is the only real rollback.
14. **You cannot `DELETE` or `MERGE` a pipeline-managed table from outside.** Unity Catalog blocks
    it, so every fix for bad rows goes through the pipeline definition. Classify the cause first: a
    full refresh reproduces replayed duplicates faithfully.
15. **A layout change needs a full refresh; `DROP TABLE` does not reset the checkpoint.**
    `partition_cols` and clustering are mutually exclusive, and the tracked layout survives a manual
    drop — so the conflict error returns on the next incremental update.

### Deploying a bundle

1. **Resource keys are GLOBALLY unique** across *all* resource types, not per type.
   `resources.pipelines.foo` + `resources.postgres_projects.foo` → `bundle validate` error
   "Duplicate key foo". The key is bundle-internal and separate from the deployed `name`/`id`, so
   rename freely.
2. **`workspace.host` is NOT `${var.*}`-interpolatable.** Host resolves during auth config *before*
   bundle variables expand, so `${var.host}` leaks literally → `invalid character "{" in host name`.
   Keep it literal, per-target, or in `DATABRICKS_HOST`/a profile.
3. **`mode: development` renames resources.** The CLI prefixes every resource with `[dev <user>]`
   and pauses schedules. Deploy anything whose name must stay stable — serverless endpoints are
   **workspace-global** — from a `production`-mode target; `presets.name_prefix: ""` does **not**
   work in dev mode (Go treats empty string as unset and re-applies the prefix).
4. **`include:` is top-level only.** There is no `targets.<t>.include`, so a globally-included
   pipeline or job can't be excluded from a target — scope per target by nesting under
   `targets.<t>.resources`. `mode:` written inside an included resource file is ignored.
5. **Maps deep-merge, arrays replace.** A per-target job override must restate the FULL `tasks:`
   list; a per-target pipeline `configuration:` need only add or override keys.
6. **`${bundle.target}` substitutes verbatim** — no case or hyphen transforms. Target
   `fiat-individual` → schema `..._fiat-individual`, an awkward UC identifier; hardcode the schema
   for such targets.
7. **Never deploy to a shared or prod target without explicit instruction**, and keep bundle *tests*
   read-only (`bundle validate`) — never auto-deploy, even behind a flag.
8. **A default that production does not override reaches production.** In the source project a
   production data-quality stage read one named individual's personal development schema, because
   `prod` never overrode the default. Give risky variables **no default**, or override them in every
   target.
9. **Configuration set only in `dev` leaves every other target on an unrecorded platform default.**
   Retry counts, flow retries, idle shutdown, row caps: set them everywhere, even to the default's
   own value.
10. **A schedule is a latency decision.** `pause_status`, the cron and `max_retries: 0` together
    decide how long a change can go undetected — a weekly cron with no retries means one transient
    failure costs a full week. `max_concurrent_runs: 2` is needed if a task pauses its own job's
    schedule.
11. **An undeclared field is not at its default — it is owned by whoever last used the UI.** A job
    was found running `max_concurrent_runs: 4` that appears nowhere in the bundle; it had been
    clicked months earlier and drifting ever since. Declare the settings that matter explicitly,
    even at the default value, so a deploy has the authority to put them back.
12. **A static wheel version makes serverless serve stale code.** Serverless caches its environment
    by dependency set, so an unchanged version string never invalidates it and a successful deploy
    changes nothing that runs. That is what `dynamic_version: true` is for — and it patches only
    *local* wheels built during the deploy, never one already in a volume or an index.
13. **Secrets do not reach a serverless pipeline through `{{secrets/...}}`.** That form resolves in
    a cluster `spark_conf`, which a serverless pipeline cannot have; in the pipeline
    `configuration:` block `spark.conf.get()` returns the literal braces with no error. Pass scope
    and key *names* as configuration and call `dbutils.secrets.get()` at module scope.
14. **Some Lakebase objects resist declaration.** Granting a role `TO authenticator` fails while
    that role carries `DATABRICKS_SUPERUSER` membership — strip it by omitting `membership_roles:`
    in the bundle, not by editing the UI, which the next deploy overwrites. Where a step genuinely
    must be imperative, put it behind a `job_runs` post-deploy hook rather than running it by hand.

### Using the platform

1. **Run an inventory query as a metastore admin**, or accept that it is partial —
   `information_schema` is filtered by the caller's grants and excludes `hive_metastore` entirely
   (list those with `SHOW TABLES IN hive_metastore.<schema>`).
2. **Never trust `CREATE TABLE IF NOT EXISTS … AS SELECT` to refresh data.** Use `OR REPLACE` or
   `MERGE`, as above.
3. **`SYNC … DRY RUN` before a real `SYNC`**; it upgrades external tables only. Copy a managed Hive
   table with `DEEP CLONE` instead.
4. **Check `DESCRIBE HISTORY` retention before you promise a rollback point.** `VACUUM` and
   `delta.logRetentionDuration` / `delta.deletedFileRetentionDuration` bound how far back you can
   travel.
5. **Match lowercase, and filter.** Identifiers are stored lowercase, so compare them directly
   instead of wrapping a column in `LOWER()`, and filter by `table_catalog` / `table_schema` —
   `LIMIT` is not pushed down and a broad scan can time out.

## Quick symptom → fix index

**Pipelines**

| Symptom | Likely cause / fix | Reference |
|---|---|---|
| "Expected a streaming source" / "expected batch" | Streaming table with a batch read, or the reverse | sdp-python-api |
| UDF fails with no `spark` / `dbutils` | Config read on the executor — move it to module scope | sdp-python-api |
| Violating rows appear in the published table | Bare `expect_all` is advisory by design | sdp-expectations-policy |
| Quality metrics show ~100% violations | A presence rule copied downstream and applied to an optional column | sdp-expectations-policy |
| Violation count permanently inflated | A rule treats every retry as a failure | sdp-expectations-policy |
| An expectation can only ever pass | Self-referential check (hash vs recomputation of itself, same row) | sdp-expectations-policy |
| Event-log query over-counts failures | Data-quality counters are cumulative — `MAX` per flow, then `SUM` | sdp-event-log-and-observability |
| Event-log query returns nulls | `details` is a variant: `details:path`, while struct fields use `origin.field` | sdp-event-log-and-observability |
| `print()` output nowhere to be found | Serverless: no Spark UI, no Spark logs, no executor route | sdp-event-log-and-observability |
| Pipeline update fails after a schema cleanup | The published event log or its schema was dropped | sdp-event-log-and-observability |
| Need to refresh one table, UI only offers all | Selective full refresh via SDK/CLI — no UI click-path | sdp-operations-and-refresh |
| Full refresh didn't recover the missing data | The source no longer offers it; refresh resets your position only | sdp-operations-and-refresh |
| Changing a streaming source forces a full refresh | Checkpoint is bound to the source; expect duplicates on an unkeyed target | sdp-operations-and-refresh |
| Downstream table duplicates on every run | `ignoreChanges` against a full-recompute upstream | sdp-operations-and-refresh |
| Streaming dedup state grows without bound | `dropDuplicates` with no watermark | sdp-operations-and-refresh |
| Many small files / most rows in one partition | `partition_cols` on a mostly-null column, or partitioning while writing single-partition | sdp-operations-and-refresh |
| Nobody knows how many times prod retries | Retry settings only configured in `dev` | sdp-operations-and-refresh |
| Need CDC / SCD semantics | `dp.create_auto_cdc_flow` (Databricks-only) | sdp-auto-cdc |
| `LIVE.` prefix silently ignored | Default publishing mode — use unqualified names | sdp-pipelines-editor-and-publishing |
| Pyright flags a kwarg that works at runtime | OSS wheel ships narrower signatures — add a local stub tree | sdp-vs-databricks-and-naming |
| Cyclic-dependency error on a table that reads itself | The graph follows the *returned* plan's lineage; renaming to a published name changes nothing | sdp-python-api |
| `spark.catalog.tableExists` missing inside a pipeline | The Python catalog API is not wired up in pipeline context — query `information_schema` | sdp-python-api |
| Analysis/graph resolution times out | A blocking network call in a dataset function body, which runs at analysis time | sdp-python-api |
| Event-log timestamps are an hour out | The column is UTC — `from_utc_timestamp` with a named zone, or set `spark.sql.session.timeZone` | sdp-event-log-and-observability |
| `ORDER BY timestamp` returns events out of order | Timestamps tie inside a millisecond — order by `sequence.data_plane_id.seq_no`, after checking `instance` is uniform | sdp-event-log-and-observability |
| Microbatch detail missing from the pipelines UI | `level: METRICS` events are table-only; `stream_progress` never appears in the UI | sdp-event-log-and-observability |
| `readStream` on the event log fails | The `event_log()` TVF is batch-only — stream a UC view over it instead | sdp-event-log-and-observability |
| Need a custom metric per flow | No API writes custom events; use a named always-true expectation as a counter | sdp-event-log-and-observability |
| Violating rows need inspecting, not counting | `_or_drop` leaves only a count — add a quarantine table and make the split null-safe | sdp-expectations-policy |
| Repointing a join's static side didn't exclude bad rows | A left join yields NULL rather than dropping — use an inner join or an explicit filter | sdp-expectations-policy |
| `CANNOT_UPDATE_PARTITION_COLUMNS` persists after `DROP TABLE` | The flow checkpoint still records the old layout — full refresh | sdp-operations-and-refresh |
| `maxFilesPerTrigger=1` no longer yields small microbatches | `cluster_by_auto` on the producer compacts files away | sdp-operations-and-refresh |
| One table failed and everything refreshed | The job task's `max_retries`, not the pipeline — recovery scope is hardcoded to refresh-all | sdp-operations-and-refresh |
| Per-key API cursors need an offsets table | They don't — a custom `DataSourceStreamReader` keeps offsets in the checkpoint | sdp-custom-data-sources |
| Need drift detection, not per-run quality | Lakehouse Monitoring attaches to the published table, not the pipeline | uc-monitoring-and-profiling |

**Bundles**

| Symptom | Likely cause / fix | Reference |
|---|---|---|
| `Duplicate key <k>` at validate | Two resources (any types) share a key — rename one | dab-resources-and-deploy |
| `invalid character "{" in host name` | `${var.*}` in `workspace.host` — use a literal | dab-variables-and-interpolation |
| Endpoint deployed as `dev_<user>_<name>` | Dev-mode prefix; deploy the endpoint from a prod target | dab-targets-and-modes |
| Per-target job lost its tasks | Array replace — restate the full `tasks:` list | dab-variables-and-interpolation |
| `CATALOG_DOES_NOT_EXIST` on synced table | `synced_table_id` is a literal 3-part name; point `catalog` at a real catalog | dab-resources-and-deploy |
| `field data_synchronization_status not found` | Use `...status.pipeline_id` for autoscaling synced tables | dab-resources-and-deploy |
| Post-deploy run needed | `job_runs` resource (CLI ≥ 1.7.0 + direct engine); `scripts` are manual only | dab-resources-and-deploy |
| "Required variable" never raised | A no-default var is enforced only when the selected target references it | dab-variables-and-interpolation |
| Production reads a developer's schema | A variable default no target overrode | dab-targets-and-modes |
| A "shared, near-production" target behaves per-user | It carries `mode: development` | dab-targets-and-modes |
| Endpoint exists in one environment, missing in another | It is workspace-global and only one target declares it | dab-targets-and-modes |
| Synced table deployed before its Lakebase branch | Branches are referenced by literal path — no bundle ordering | dab-lakebase |
| Data API returns 403 for a granted principal | Role not granted `TO authenticator`, or created via `postgres_roles` | dab-lakebase |
| Data API 403 only on newly added tables | `GRANT … ON ALL TABLES` is a snapshot; re-run or set default privileges | dab-lakebase |
| New schema invisible over the Data API | It is not in the Data API's `db_schemas` list | dab-lakebase |
| `42501 permission denied to set role` over the Data API | `authenticator` was never granted the role | dab-lakebase |
| `permission denied to grant role` when fixing the above | The role carries `DATABRICKS_SUPERUSER` — omit `membership_roles:` in the bundle | dab-lakebase |
| Row-level security ignored for API traffic | A superuser role carries `BYPASSRLS` | dab-lakebase |
| Serverless runs old code after a successful deploy | The environment cache never invalidated — `dynamic_version: true` | dab-resources-and-deploy |
| `spark.conf.get()` returns a literal `{{secrets/...}}` | The reference form is classic-compute only | administration-credential-management |
| `dbutils.secrets.get()` fails only in prod | The run-as service principal lacks `READ` on the scope | administration-credential-management |
| A setting in the workspace isn't in the bundle | It was set in the UI and is drifting — declare it explicitly | dab-targets-and-modes |
| Needed to exclude a file from a pipeline `glob` | There is no `exclude` key — narrow the include or move the file | dab-resources-and-deploy |
| `environment_version` ignored on a notebook task | Not applicable via bundle YAML for `notebook_task` | dab-resources-and-deploy |

**Platform**

| Symptom | Likely cause / fix | Reference |
|---|---|---|
| An inventory query misses tables | The caller lacks grants, or the tables live in `hive_metastore` — run as a metastore admin and query `hive_metastore` separately | uc-introspection |
| A nightly CTAS serves stale data | `IF NOT EXISTS` skipped the existing target — use `CREATE OR REPLACE` or `MERGE` | — |
| `SYNC` reports nothing to do | The source is a managed, not external, table — use `DEEP CLONE` | uc-table-migration-and-lifecycle |
| `VERSION AS OF` fails for an old version | The version fell outside the retention window | uc-table-migration-and-lifecycle |
| A secret prints as `[REDACTED]` | Expected — redaction is on the printed value, not on the read | administration-credential-management |

## Commands

```bash
databricks bundle validate -t <target>     # structural check (local); dup-key/schema errors first
databricks bundle deploy   -t <target>     # dev is the default target
databricks bundle run <job-or-pipeline-key> -t <target>
```

```sql
SELECT * FROM system.information_schema.tables WHERE table_schema = 'default';
SYNC SCHEMA main.default FROM hive_metastore.default DRY RUN;
DESCRIBE HISTORY main.default.customers;
SELECT * FROM main.default.customers VERSION AS OF 42;
RESTORE TABLE main.default.customers TO VERSION AS OF 42;
SELECT * FROM event_log;                   -- the pipeline event log, Lakeflow only
```

- `bundle validate -o json` shows the **pre-substitution** config — `${var.*}` appear
  **unexpanded**; that is NOT proof a resource ignores a variable. Interpolation happens at deploy,
  so read resolved values in the deploy request or the UC error, not in `-o json`.
- Reaching an **auth** error on `validate` means structural validation already passed (dup-key,
  schema and required-var checks run locally, before auth).

## Upstream documentation (sources)

Re-verify against these before relying on anything here.

**Pipelines**

- Apache Spark — Declarative Pipelines programming guide: <https://spark.apache.org/docs/latest/declarative-pipelines-programming-guide.html>
- Databricks — Lakeflow Declarative Pipelines (overview): <https://learn.microsoft.com/en-us/azure/databricks/ldp/>
- Databricks — Pipelines Python reference (the `dp` API): <https://learn.microsoft.com/en-gb/azure/databricks/ldp/developer/python-ref>
- Databricks — AUTO CDC: <https://learn.microsoft.com/en-us/azure/databricks/ldp/cdc>
- Databricks — Multi-file / Pipelines Editor: <https://learn.microsoft.com/en-us/azure/databricks/ldp/multi-file-editor>
- Databricks — LIVE virtual schema / publishing: <https://docs.databricks.com/aws/en/ldp/live-schema>

**Bundles**

- Databricks — Asset Bundles: <https://docs.databricks.com/dev-tools/bundles/index.html>

**Platform**

- Unity Catalog `information_schema`: <https://docs.databricks.com/en/sql/language-manual/sql-ref-information-schema.html>
- `SYNC` command: <https://docs.databricks.com/en/sql/language-manual/sql-ref-syntax-aux-sync.html>
- Delta time travel and history: <https://docs.databricks.com/en/delta/history.html>
- `MERGE INTO`: <https://docs.databricks.com/en/sql/language-manual/delta-merge-into.html>

## When to use this skill

- Writing or editing a pipeline source file; adding a table, flow, expectation or sink. Deciding
  streaming table vs materialized view, or `append_flow` vs AUTO CDC. Triaging a bad run, or
  deciding how to refresh after a logic change.
- Editing `databricks.yml` or `resources/*.yml`; adding a target, variable or resource; choosing dev
  vs prod mode; debugging name prefixing or a per-target override; wiring post-deploy automation,
  Lakebase resources, the Data API or the wheel artifact.
- Administering or inspecting a workspace's data — catalogs, schemas, tables and their history — or
  reporting on data coverage. Configuring a cluster, managing secrets, connecting an external
  source, copying files or notebooks, serving a model, or calling an LLM.
- Auditing defaults — schedules, retries, row caps — for values that exist in only one target, and
  reconciling older DLT/DAB naming against current docs.

## Related skills

- [develop-pyspark](../develop-pyspark/SKILL.md) — what goes wrong *inside* a dataset function:
  Arrow/pandas UDFs, OOM, chunking, joins and skew, and
  [model registration](../develop-pyspark/references/model-registration-and-endpoints.md) for the
  endpoints a bundle declares.
- [develop-scala](../develop-scala/SKILL.md) — a custom Spark `FileFormat` DataSource and its
  shaded packaging.
- [develop-infrastructure](../develop-infrastructure/SKILL.md) — the Azure platform the workspace,
  storage and Unity Catalog live on, underneath the bundle.
- [test-python](../test-python/SKILL.md) — testing pipeline source files that cannot be imported,
  plus bundle-validation and wheel-build tests.
