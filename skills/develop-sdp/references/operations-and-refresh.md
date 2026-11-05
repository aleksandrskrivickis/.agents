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

### Three things about full refresh that surprise people

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
    full_refresh=False,                               # not everything
    full_refresh_selection=["documents_slices"],      # just these
)
```

```bash
databricks pipelines start-update <pipeline-id> \
  --full-refresh-selection documents_slices,documents_slices_embeddings
```

Keep that as a checked-in, parameterised notebook or script. An operation you can only perform by
remembering an SDK signature under pressure is an operation you will perform wrong.

### Prefer a new flow over a full refresh

Often the best answer is to **not refresh at all**. Because each `append_flow` owns a checkpoint
keyed by its **name**, renaming the flow produces a fresh checkpoint that re-reads from the start and
**appends a new generation beside the old rows**:

```python
@dp.append_flow(target="slices", name=f"slices_{SLICER_GENERATION}")
def slices_flow():
    ...
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
> them in prod too, even if to the same value as the default. See
> [document-decisions](../../document-decisions/SKILL.md).

Separately, the **job** wrapping a pipeline has its own `max_retries` and `max_concurrent_runs`;
those are bundle-level and covered in
[databricks-asset-bundles](../../databricks-asset-bundles/SKILL.md).

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
    "quality": "bronze",                       # a convention, not a platform feature
}
```

- **Apply them consistently.** In the source project a shared `table_properties` dict existed and was
  applied to **exactly one** table out of twenty — while the project's own documentation described a
  richer dict (Change Data Feed, a quality tag) that did not exist in the code at all. A documented
  convention that isn't in the code is worse than none, because the next developer looks for a
  pattern that is not there.
- **`quality` is a tag you invent**, useful for a medallion convention and for filtering in a
  catalogue. It does nothing by itself.
- **`partition_cols` vs `cluster_by_auto=True`:** pick one per table and know why. Partitioning by a
  column that is null for most rows (a US-only state code, say) lands most rows in a single null
  partition; partitioning while writing on a single partition reliably generates many small files.
  Automatic clustering avoids both and is the better default for anything you aren't sure about.
- Don't mix auto-optimize with a stage whose correctness depends on a one-file-per-window commit
  cadence — compaction breaks the 1:1 mapping. See
  [throughput-and-partitioning](../../develop-pyspark/references/throughput-and-partitioning.md).

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
[event-log-and-observability.md](./event-log-and-observability.md).

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

- [expectations-policy.md](./expectations-policy.md) — whether your quality rules can stop anything.
- [event-log-and-observability.md](./event-log-and-observability.md) — the triage substrate.
- [databricks-asset-bundles](../../databricks-asset-bundles/SKILL.md) — schedules, job retries, and
  per-target configuration.
