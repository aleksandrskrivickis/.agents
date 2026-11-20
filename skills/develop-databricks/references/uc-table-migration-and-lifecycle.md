# Table migration and lifecycle in depth

> **Source.** The Databricks `SYNC`, `CREATE TABLE … CLONE`, and "Work with table history"
> references, verified against the live docs on 2026-11-06. Confidence tags: `[docs]` a documented
> behaviour, `[deduced]` an inference, `[?]` worth verifying.

## `SYNC`: upgrading Hive metastore tables

`SYNC` registers a Hive metastore table as a Unity Catalog table. It upgrades **external** tables
directly. A **managed** Hive table needs more care `[docs]`:

- managed and stored **outside** workspace storage (the DBFS root) → add `AS EXTERNAL`;
- managed and stored **inside** workspace storage → `SYNC` cannot do it; use
  `CREATE TABLE … DEEP CLONE …` instead.

**`SYNC` writes to the source.** It runs an `ALTER TABLE` on each source table to record an
`upgraded_to` bookkeeping property, so the running compute needs **write access** to the source
location. To stop that write, set `spark.databricks.sync.command.disableSourceTableWrites = true`
before the command; `SYNC` then relies on the table name alone to decide whether it already upgraded
a table. `[docs]`

### Status codes worth knowing `[docs]`

`SYNC` returns one row per table with a `status_code`. The ones you will meet:

| Code | Meaning and action |
|---|---|
| `DRY_RUN_SUCCESS` | The table can be upgraded. |
| `SUCCESS` | Upgraded. |
| `NOT_EXTERNAL` | The source is managed. Use `AS EXTERNAL` or `DEEP CLONE`. |
| `DBFS_ROOT_LOCATION` | The table sits in the DBFS root. `DEEP CLONE` it. |
| `HIVE_SERDE` | A Hive SerDe table. Convert it to Delta first. |
| `TABLE_ALREADY_EXISTS` | A table of that name already exists in UC. Rename or drop it. |
| `MULTIPLE_TARGET_TABLE` | The source was already synced elsewhere. Remove its `upgraded_to` property to force a new target. |
| `TIMEOUT` | The task passed 600 s. Raise `spark.databricks.sync.command.task.timeout` (table) or `…task.create.timeout` (schema). |

### A corruption trap `[docs]`

Hive metastore may store table comments in `latin1`. `SYNC` can then render non-ASCII comments
(Japanese, Chinese) as `???`. Repair them in Unity Catalog with:

```sql
MSCK REPAIR TABLE main.default.my_table SYNC METADATA;
```

## `DEEP CLONE` versus `SHALLOW CLONE` `[docs]`

- **`DEEP CLONE`** copies the data and the metadata. The clone is independent.
- **`SHALLOW CLONE`** copies only the metadata and points at the source's data files. It is cheap,
  but it **breaks if the source is `VACUUM`-ed**, because the referenced files disappear. `[deduced]`

## Time travel, retention, and `RESTORE`

Query a past version by number or timestamp `[docs]`:

```sql
SELECT * FROM main.default.customers VERSION AS OF 42;
SELECT * FROM main.default.customers TIMESTAMP AS OF '2026-01-01';
RESTORE TABLE main.default.customers TO VERSION AS OF 42;
```

How far back you can travel depends on two retention settings `[docs]`:

- `delta.logRetentionDuration` — how long history is kept (default **30 days**);
- `delta.deletedFileRetentionDuration` — how long `VACUUM` keeps old data files (default **7 days**).

You need **both** the log entry and the data files for a version. On recent runtimes a time-travel
query is **blocked** if it asks for a version older than `deletedFileRetentionDuration`. Raise both
settings together if you must travel further back; expect a higher storage cost.

**`RESTORE` is a data-changing operation.** It needs `MODIFY`, and it cannot reach a version whose
files were already `VACUUM`-ed. It also writes `dataChange = true` log entries, so a downstream
**Structured Streaming** reader sees the restored files as **new data** and can produce duplicates.
Plan for that before you restore a table that feeds a stream. `[docs]`
