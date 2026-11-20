# Operating a pipeline: refresh, retries, and triage

> **Source.** `[repo]` — from a production Lakeflow pipeline's operational history: the refresh
> gotchas it hit, the retry settings it landed on, and the triage queries it wrote after an
> incident. `[docs]` marks documented Databricks behaviour; `[deduced]` an inference.

Writing a pipeline is one skill; running one is another. Most of this file is about **refresh
semantics**, because that is where correct-looking operations destroy data or fail to recover it.

## The refresh options, and what each one actually does

| Operation | Effect | Reach for it when |
|---|---|---|
| **Update** (default run) | Processes new data from each flow's checkpoint | Normal operation |
| **Full refresh** | **Truncates the target and reprocesses from the source's beginning**, resetting the checkpoint | The *derivation* changed and old rows are wrong |
| **Selective full refresh** | Full-refreshes named tables only; others update normally | One stage's logic changed and the corpus is large |
| **Refresh all / Validate** | Validate parses and plans without writing | Pre-deploy check |

### Four things about full refresh that surprise people

**1. A full refresh cannot recover data the source no longer offers.**

> "A full refresh is not a mitigation either."

This was recorded as a correction to an earlier claim in the source project, and it is the most
important sentence here. If ingestion only ever moves *forward* — a resume offset, an append-only
source, a vendor API paginated by cursor — then a full refresh re-reads **the source as it is
today**, not as it was. Documents amended in place, or dropped from the source, do not come back.
Full refresh resets *your* position, not the world's history.

**2. Changing a streaming source forces one.**

A streaming flow's checkpoint is bound to its source. Change the source table, the read options in
ways that affect progress tracking, or the flow's identity, and the flow cannot resume — it needs a
full refresh, which means reprocessing everything. On an append-only target that also means
**duplicates** unless the target is keyed.

**3. Selective full refresh has no UI click-path.**

The UI offers full refresh of everything, or nothing. To refresh named tables only, go through the
API/CLI — the source project kept an operations notebook for exactly this, with the comment
"because the UI has no click-path":

```python
from databricks.sdk import WorkspaceClient

w = WorkspaceClient()
w.pipelines.start_update(
    pipeline_id=PIPELINE_ID,
    full_refresh=False,  # not everything
    full_refresh_selection=["documents_slices"],  # just these
)
```

```bash
databricks pipelines start-update <pipeline-id> \
  --full-refresh-selection documents_slices,documents_slices_embeddings
```

Keep that as a checked-in, parameterised notebook or script. An operation you can only perform by
remembering an SDK signature under pressure is an operation you will perform wrong.

**4. There is no pipeline-level rollback to fall back on.**

An update is **not one transaction across the graph** — each flow commits to its own target
independently, so there is no consistent cut to return to. "Put the pipeline back to 14:00
yesterday" is not an operation; the best you can reconstruct is a set of per-table versions that
happened to be current at the same wall-clock moment. What you actually have:

| Primitive | On a streaming table | On a materialized view |
|---|---|---|
| `RESTORE TABLE … TO VERSION AS OF n` | Restores the data and **leaves the checkpoint ahead of it** | Not supported `[?]` |
| Full refresh | Recompute from source with *current* code | The only recompute path |
| `DEEP CLONE` taken **before** the deploy | The real rollback | The real rollback |

The checkpoint is the trap. `RESTORE` moves the Delta table back, but the flow still believes it
consumed those offsets and will not re-emit them — leaving a **permanent hole**. Restore is only
safe if you also reset the flow, at which point you are doing a full refresh anyway.

So the strategy has to be *before*, not *after*:

- `CREATE TABLE bak.x_<version> DEEP CLONE catalog.schema.x` for the tables you could not re-derive,
  as a deploy step. Managed-table retention is not something to discover during an incident.
- Set `pipelines.reset.allowed = false` on any table where reprocessing would be destructive — an
  ingest table whose source has moved on, an append-only audit log. It makes the dangerous operation
  refuse rather than succeed quietly.
- To find *which* versions to target, the event log gives you the `update_id` boundaries; cross-
  reference `DESCRIBE HISTORY` per table for the last commit before the bad update.

The common case needs none of this: revert the code, redeploy the prior artifact, and
selectively full-refresh the affected tables. Reach for the clone only when the source cannot
re-derive the rows.

### Prefer a new flow over a full refresh

Often the best answer is to **not refresh at all**. Because each `append_flow` owns a checkpoint
keyed by its **name**, renaming the flow produces a fresh checkpoint that re-reads from the start and
**appends a new generation beside the old rows**:

```python
@dp.append_flow(target="slices", name=f"slices_{SLICER_GENERATION}")
def slices_flow(): ...
```

- No truncation, so prior results stay queryable and comparable.
- Consumers filter to the generation they want.
- The cost is storage — a corpus copy per generation — so decide retention when you adopt it.

Key the name on whatever identity makes outputs comparable: the model for embeddings, a config
digest for chunking. See
[chunking-and-embedding-fit](../../develop-pyspark/references/chunking-and-embedding-fit.md).

> **A generation stamp added late leaves unstamped rows.** In the source project a third of the
> table predated the stamp. Have an explicit policy for nulls — exclude or backfill — before the
> first consumer filters on it.

## Retry and lifecycle configuration

Set in the pipeline resource's `configuration:` block (Spark confs), per target:

```yaml
configuration:
    # Do not relaunch the whole update when it fails. Without this, a failing update
    # retries from the top and the failure is harder to see in the event log.
    pipelines.numUpdateRetryAttempts: "0"
    # dev: fail fast, no within-update flow retries.
    pipelines.maxFlowRetryAttempts: "0"
    # Keep dev compute warm between iterations (costs money while idle).
    pipelines.clusterShutdown.delay: 3600s
```

| Setting | Scope | Notes |
|---|---|---|
| `pipelines.numUpdateRetryAttempts` | The whole update | `"0"` stops an automatic relaunch on failure. Worth setting explicitly in every target. |
| `pipelines.maxFlowRetryAttempts` | One flow within an update | `"0"` = fail fast; good in dev, a real decision in prod |
| `pipelines.clusterShutdown.delay` | Compute idle time | A recurring cost with no natural owner — set it per target, not globally |

> **Leaving these unset in production is itself a decision.** The source project set both retry
> counts in `dev` only, with the result that nobody could state how many times a production flow
> retried before failing — the platform default is not recorded anywhere. If you set them in dev, set
> them in prod too, even if to the same value as the default.

### Two retry layers, and the one you are probably seeing

Separately, the **job** wrapping a pipeline has its own `max_retries` and `max_concurrent_runs`;
those are bundle-level and covered in
[dab-resources-and-deploy.md](./dab-resources-and-deploy.md). The distinction matters more than it
looks, because the two layers produce the same symptom and only one of them is configurable:

- **The pipeline's own automatic recovery only handles infrastructure failures** — cluster startup,
  credentials — not table or data logic errors. `[docs]`
- **Its scope is hardcoded to `refresh all`.** There is no setting that gets you `scope=failed`; the
  `pipeline_task` schema accepts only `pipeline_id` and `full_refresh`, with no retry surface at
  all. Selective recovery means driving `start_update` yourself (above).
- So **"one table failed and the whole pipeline refreshed everything" is almost always the job
  task's `max_retries`** re-running the `pipeline_task`, which starts a fresh refresh-all update.
  Pin it to `0` in the bundle and the behaviour stops. `[repo]`

### `spark_conf` has three scopes, and serverless narrows them

Spark properties can be set for the whole pipeline (the `configuration:` block above), for one of
its compute resources, or for **an individual flow, materialized view or streaming table** via
`spark_conf=` on the decorator — where the decorator wins over the pipeline. `[docs]`

```python
@dp.table(spark_conf={"spark.sql.execution.arrow.maxRecordsPerBatch": "5000"})
def my_table(): ...
```

Set it at pipeline level when you want it everywhere; set it on the decorator when one flow needs a
different batch size, trigger interval or shuffle width. The caveat is serverless: plain serverless
notebooks and jobs expose only a short allow-list (timezone, ANSI mode, shuffle partitions), and
`arrow.maxRecordsPerBatch` is not on it. SDP's decorator path is documented as a separate, broader
mechanism — but a property that falls under the serverless restriction is dropped wherever you set
it (`spark.driver.maxResultSize` is on record failing with `CONFIG_NOT_AVAILABLE`). Set it on the
decorator, then **confirm it was honoured rather than silently dropped** before you build a memory
budget on it. `[?]`

## `ignoreChanges` on a full-recompute upstream duplicates rows

A trap with a long, quiet fuse:

```python
# jurisdictions_latest is a @dp.table — a full recompute, so every run rewrites its files.
spark.readStream.option("ignoreChanges", "true").table("jurisdictions_latest")
```

`ignoreChanges` tells the stream to tolerate rewritten files by **re-emitting them**. Against a
materialized view or `@dp.table` that recomputes fully, *every file is rewritten every run*, so the
entire upstream is re-emitted downstream on every run.

What makes it invisible is the usual next move:

```python
.dropDuplicates(["document_id"])       # absorbs the duplication...
```

…which hides the symptom **and** grows unbounded state, because a `dropDuplicates` on a stream with
no watermark must remember every key forever.

| Option | Behaviour | Use for |
|---|---|---|
| `ignoreChanges` | Re-emits rewritten files (duplicates possible) | A source with occasional compaction, where the target is keyed/idempotent |
| `skipChangeCommits` | **Skips** commits that update/delete, processing only appends | An append-only logical source whose files get rewritten — usually what you actually want |

- Against a full-recompute upstream, prefer **`skipChangeCommits`**, or restructure so the stream
  reads an append-only table.
- If you must dedup on a stream, **add a watermark** and bound the key space, and record why the
  window is what it is.

## Table properties and physical layout

```python
table_properties = {
    "pipelines.autoOptimize.managed": "true",
    "quality": "bronze",  # a convention, not a platform feature
}
```

- **Apply them consistently.** In the source project a shared `table_properties` dict existed and was
  applied to **exactly one** table out of twenty — while the project's own documentation described a
  richer dict (Change Data Feed, a quality tag) that did not exist in the code at all. A documented
  convention that isn't in the code is worse than none, because the next developer looks for a
  pattern that is not there.
- **`quality` is a tag you invent**, useful for a medallion convention and for filtering in a
  catalogue. It does nothing by itself.
- **`partition_cols` vs `cluster_by_auto=True`:** pick one per table and know why. They are
  **mutually exclusive** in Delta, so this is a layout commitment, not a tuning knob. Partitioning
  by a column that is null for most rows (a US-only state code, say) lands most rows in a single
  null partition; partitioning while writing on a single partition reliably generates many small
  files. Automatic clustering avoids both and is the better default for anything you aren't sure
  about — but see the compaction interaction below before putting it on a table something else
  streams from.

### Changing the layout needs a full refresh — `DROP TABLE` will not do it

```
[CANNOT_UPDATE_PARTITION_COLUMNS] Declared partitioning jurisdiction_country, jurisdiction_state,
portal_name conflicts with existing table partitioning . Please delete the table or change the
declared partitioning to match its partitions.
```

The error tells you to delete the table. **Deleting the table does not fix it.** A streaming table
is pipeline-managed, and a manual `DROP TABLE` does not reset the flow's checkpoint — the tracked
layout (here: empty partitioning, because the table used to be a materialized view with
`cluster_by`) survives, so the next incremental update re-materialises with the old layout and the
same error comes back. `[repo]`

Only a **full refresh** clears the checkpoint and rebuilds with the declared `partition_cols`. And
because full-refreshing a table restarts its version history, every checkpoint-bearing consumer
downstream has to be refreshed too — so **a full-pipeline refresh is the safe default** for a layout
change, not a selective one.

> **Clustering on the producer defeats microbatch sizing on the consumer.** `cluster_by_auto=True`
> triggers auto-compaction that merges files. A downstream flow reading that table with
> `maxFilesPerTrigger=1` can then no longer get small microbatches — there are no small files left
> to hand it. If a consumer's memory budget depends on tiny batches, the producer cannot be
> auto-clustered; partition it instead. This is the specific, non-obvious case behind the general
> warning below. `[repo]`
- Don't mix auto-optimize with a stage whose correctness depends on a one-file-per-window commit
  cadence — compaction breaks the 1:1 mapping. See
  [throughput-and-partitioning](../../develop-pyspark/references/throughput-and-partitioning.md).

## You cannot DML your way out of bad rows

Before planning any fix, know the constraint that removes most of the obvious options: **streaming
tables and materialized views are pipeline-managed, so an external `DELETE` or `MERGE` against them
is blocked in Unity Catalog.** "Just delete the duplicates" is not available. Every real fix goes
through the pipeline definition. `[repo]`

So when a run produces millions of rows it should not have, the first job is classification, because
each cause has a *signature* and a different fix:

| Cause | Signature | Fix |
|---|---|---|
| **Source replay** — checkpoint reset, an accidental full refresh on a still-retained source, Auto Loader re-listing after a path change | Exact row copies; count is a clean multiple of the original | A full refresh **faithfully reproduces them**. Dedupe at read time with `dropDuplicatesWithinWatermark`, or restructure the target as AUTO CDC keyed on the natural key with `sequence_by` on ingest time, which collapses repeats idempotently |
| **Join fanout** — a lookup or dimension picked up duplicate keys, so 1:1 became 1:N | Duplication factor **varies by key** | Fix the code, full-refresh the table and everything downstream. The good case: the rows were never in the source, so recomputation genuinely removes them |
| **CDC misconfiguration** — wrong `keys`, or `sequence_by` on a non-unique column | Updates landed as inserts | Fix the flow definition, then full refresh |

The event log tells you which update did it; the spike lines up with a commit in
`DESCRIBE HISTORY` on the target:

```sql
SELECT timestamp, origin.flow_name, origin.update_id,
       details:flow_progress.metrics.num_output_rows
FROM event_log(TABLE(catalog.schema.pipeline))
WHERE event_type = 'flow_progress'
ORDER BY timestamp DESC;
```

If bronze itself is contaminated and cannot be re-derived, the escape hatch is to materialise a
clean copy outside the pipeline (`CREATE TABLE recovery.x AS SELECT DISTINCT … FROM bronze.x`),
repoint bronze's source at it, and full refresh. It is ugly and it is sometimes the only option.
**`DEEP CLONE` the affected tables before you refresh anything** — even contaminated, that is your
only rollback if the refresh comes back wrong.

## A triage playbook for "the table looks wrong"

Four checks, in order, each of which *eliminates* a class of cause. This came out of a real incident
and it is worth having written down before the next one.

| # | Check | Query shape | Reads as |
|---|---|---|---|
| **1** | **Source health** | Total / success / failed rows, `failed_pct`, and a breakdown by status code | Low failures ⇒ not a source problem; move on |
| **2** | **Run history** | One row per run marker (`pipeline_timestamp` / `update_id`) with rows added and the acquired-time span | Few, only-recent runs ⇒ the table was rebuilt, not under-filled |
| **3** | **Coverage** | How far through the source you have read (`max(offset_end)`) vs what the source says it has (`total_count`), as an overall percentage and a per-partition "most remaining" list | Large remaining ⇒ you are simply mid-backfill |
| **4** | **Resume state** | How many keys sit at the initial offset vs advanced | Many at zero ⇒ resume state was reset, or never persisted |

Why the order matters: each check is cheap and rules out everything below it. Running check 4 first
produces a confident wrong answer, because a reset resume state and a never-populated one look
identical unless you already know the table was not rebuilt.

> **Check 4 found a silent, total failure in the source project**: the resume-offsets table was
> empty, so the maintenance merge that writes it had never run, and **every key restarted from zero
> on every run**. A correct, unit-tested fix for a related bug had been sitting inert for weeks
> because of it. "The fix is merged" and "the fix has run" are different states — track them
> separately.

Pair the playbook with the event log for the execution half — flow status, row counts and
expectation counts per update — see
[sdp-event-log-and-observability.md](./sdp-event-log-and-observability.md).

## Pre-deploy and pre-refresh checklist

1. Does this change alter a **derivation**? If so, a refresh is needed — can it be a new flow
   generation instead of a truncating full refresh?
2. Does it change a **streaming source** or a flow name? Then a full refresh is forced; is the
   target keyed, or will you get duplicates?
3. If a full refresh is genuinely needed: is the data still **obtainable** from the source? (See the
   first gotcha above.)
4. Can you do it **selectively**? Name the tables rather than refreshing everything.
5. Are retry settings explicit in **this** target, not just in `dev`?
6. After deploying: has the change actually **run**, and did you look at the event log to confirm it
   — not just the deploy output?

## Related

- [sdp-expectations-policy.md](./sdp-expectations-policy.md) — whether your quality rules can stop anything.
- [sdp-event-log-and-observability.md](./sdp-event-log-and-observability.md) — the triage substrate.
- [dab-resources-and-deploy.md](./dab-resources-and-deploy.md) — schedules, job retries, and the
  `pipelines:` resource block.
- [dab-targets-and-modes.md](./dab-targets-and-modes.md) — why per-target configuration must be set
  everywhere, not only in `dev`.
