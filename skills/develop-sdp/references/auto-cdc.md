# AUTO CDC (change data capture)

`AUTO CDC` and `AUTO CDC FROM SNAPSHOT` automate slowly-changing-dimension (SCD) Type 1/2 upkeep of
a target streaming table from a change feed or from snapshots. They **replace the `APPLY CHANGES`
APIs** and share the same syntax — `APPLY CHANGES` still works, but Databricks recommends AUTO CDC.

> **Lakeflow-only.** The AUTO CDC APIs are **not** part of Apache Spark Declarative Pipelines. They
> require serverless Lakeflow pipelines or the `Pro`/`Advanced` editions. This repo does not
> currently use CDC (it does custom version pairing via `applyInPandasWithState` in stage 02-01),
> but this is the API to reach for if/when CDC is adopted.

## Which API

- **`AUTO CDC`** — source database already emits a change data feed (CDF). Python
  `create_auto_cdc_flow()`, SQL `AUTO CDC ... INTO`.
- **`AUTO CDC FROM SNAPSHOT`** — only periodic snapshots are available; it diffs successive
  snapshots to derive changes. Python `create_auto_cdc_from_snapshot_flow()`, SQL `AUTO CDC ... FROM SNAPSHOT`.
- For SCD Type 1 targets you can combine one `FROM SNAPSHOT` flow with one or more `AUTO CDC` flows.

## `create_auto_cdc_flow` arguments

| Arg | Required | Meaning |
|---|---|---|
| `target` | yes | Target streaming table (defined with `create_streaming_table`) |
| `source` | yes | Name of the CDC source dataset (a streaming read) |
| `keys` | yes | Column(s) identifying a row; unqualified identifiers (`"id"`, not `"src.id"`) |
| `sequence_by` | yes | Expression ordering events per key; highest wins. Any orderable SQL expr/Column, incl. a `struct(...)`. Must be non-null and type-stable across runs |
| `apply_as_deletes` | no | Boolean expr marking delete events (e.g. `"op = 'DELETE'"`) |
| `apply_as_truncates` | no | Boolean expr marking truncate events |
| `column_list` / `except_column_list` | no | Keep-only vs drop columns (mutually exclusive); commonly `except_column_list=["op","sequenceNum"]` |
| `stored_as_scd_type` | no | `1` (overwrite, no history) or `2`/`"2"` (history with `__START_AT`/`__END_AT`) |
| `track_history_except_column_list` | no | SCD2 only: columns whose changes do **not** create a new version |
| `name`, `spark_conf` | no | Flow name (defaults to target); per-flow Spark conf |

### Python example (SCD Type 1)

```python
from pyspark import pipelines as dp
from pyspark.sql.functions import col, expr


@dp.view
def users():
    return spark.readStream.table("main.cdc_tutorial.users_cdf")


dp.create_streaming_table("users_current")

dp.create_auto_cdc_flow(
    target="users_current",
    source="users",
    keys=["userId"],
    sequence_by=col("sequenceNum"),
    apply_as_deletes=expr("operation = 'DELETE'"),
    apply_as_truncates=expr("operation = 'TRUNCATE'"),
    except_column_list=["operation", "sequenceNum"],
    stored_as_scd_type=1,
)
```

### SQL equivalent

```sql
CREATE OR REFRESH STREAMING TABLE users_current;

CREATE FLOW apply_cdc AS AUTO CDC INTO users_current
FROM stream(main.cdc_tutorial.users_cdf)
KEYS (userId)
APPLY AS DELETE WHEN operation = "DELETE"
APPLY AS TRUNCATE WHEN operation = "TRUNCATE"
SEQUENCE BY sequenceNum
COLUMNS * EXCEPT (operation, sequenceNum)
STORED AS SCD TYPE 1;
```

Multi-column sequencing: `sequence_by = struct("timestamp_col", "id_col")` (SQL `SEQUENCE BY
STRUCT(...)`) — ordered by the first field, ties broken by the next.

## `create_auto_cdc_from_snapshot_flow`

```python
dp.create_streaming_table("target")
dp.create_auto_cdc_from_snapshot_flow(
    target="target",
    source="source",  # a view, OR a next_snapshot_and_version(latest) -> (df, version) function
    keys=["userId"],
    stored_as_scd_type=2,
)
```

Python uses pipeline update order for versioning, or a `next_snapshot_and_version(latest_version)`
function returning `(DataFrame, version)` for explicit ordering. SQL uses a `FROM SNAPSHOT (...)` +
`WITH VERSION (...)` clause. Use `once=True` (SQL `ONCE`) to backfill a single snapshot while AUTO
CDC flows continue.

## Requirements and gotchas

- Target must be a **streaming table** whose format supports **row-level MERGE** (DSv2
  `SupportsRowLevelOperations`). Delta on Databricks qualifies; plain **Parquet does not** →
  fails at startup with `AUTOCDC_TARGET_DOES_NOT_SUPPORT_MERGE`.
- Target must have **exactly one** input flow (`AUTOCDC_MULTIPLE_FLOWS_TO_TARGET` otherwise) — no fan-in.
- Source must be a **streaming** read; the catalog metadata must persist across runs.
- `sequence_by`: orderable, never null (`NULL_SEQUENCE`), type-stable across runs
  (`SEQUENCING_TYPE_DRIFT` → needs full refresh). Within-batch ties broken arbitrarily.
- Changing the **key set/types** across runs is unsupported (`KEY_SCHEMA_DRIFT`); fully refresh the
  target to change keys: `spark-pipelines run --full-refresh <table>`.
- Reserved column prefix `__spark_autocdc_` (and SCD2 `__START_AT`/`__END_AT`) — source cannot
  contain colliding names. Let AUTO CDC derive the target schema where possible.
- Bitemporal AUTO CDC and partial updates exist (Beta); SCD2 preserves history, SCD1 keeps current only.

## Sources

- Databricks — AUTO CDC / change data capture: <https://learn.microsoft.com/en-us/azure/databricks/ldp/cdc>
