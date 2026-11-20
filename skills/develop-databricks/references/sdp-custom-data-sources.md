# Custom Python Data Sources: one offset cursor per key

> **Source.** `[repo]` — from a pipeline that pulls a paginated API with an independent cursor per
> `(iso, portal)` pair. `[docs]` marks documented PySpark/Databricks behaviour; `[deduced]` an
> inference; `[?]` a claim worth verifying before you rely on it.

The problem this solves: *incrementally pull an API where each key has its own cursor, and resume
from where the last run stopped.* The obvious design — a table holding the latest offset per key,
read back at the start of each update — puts you straight into the self-reference trap in
[sdp-python-api.md](./sdp-python-api.md). There is a better answer, and it is not a workaround:
**Spark's own offset machinery is already partition-keyed and already persisted in the pipeline's
checkpoint.** A custom streaming Data Source uses it instead of reimplementing it.

## The shape

`DataSourceStreamReader` has five methods, and the per-key cursor falls out of them for free
because offsets are keyed per partition, not globally:

```python
from pyspark.sql.datasource import DataSource, DataSourceStreamReader, InputPartition

class KeyPartition(InputPartition):
    def __init__(self, iso, name, start_offset, end_offset):
        self.iso, self.name = iso, name
        self.start_offset, self.end_offset = start_offset, end_offset

class KeyStreamReader(DataSourceStreamReader):
    def __init__(self, schema, options):
        # Discover the key set from something INDEPENDENT of this flow's target —
        # a config table, a reference dataset, a "list keys" API call.
        self.keys = get_keys(options)

    def initialOffset(self) -> dict:
        # Called only when there is no checkpoint. See "bootstrapping" below.
        return {f"{iso}|{name}": 0 for iso, name in self.keys}

    def latestOffset(self) -> dict:
        return {f"{iso}|{name}": fetch_latest_offset(iso, name) for iso, name in self.keys}

    def partitions(self, start: dict, end: dict):
        return [KeyPartition(iso, name, start[f"{iso}|{name}"], end[f"{iso}|{name}"])
                for iso, name in self.keys]

    def commit(self, end: dict):
        pass                      # Spark persists `end` in the checkpoint for you

    def read(self, partition: KeyPartition):
        yield from call_api(partition.iso, partition.name,
                            from_offset=partition.start_offset,
                            to_offset=partition.end_offset)

class KeyApiSource(DataSource):
    @classmethod
    def name(cls): return "key_api"
    def schema(self): return "iso string, name string, offset long, payload string"
    def streamReader(self, schema): return KeyStreamReader(schema, self.options)
```

Register it and read it like any other streaming source:

```python
spark.dataSource.register(KeyApiSource)

@dp.table
def raw_transactions():
    return spark.readStream.format("key_api").load()
```

No offsets table, no self-read, no `collect()`.

## What constrains it

- **Reader only, inside a pipeline.** SDP owns the write into the target streaming table, so you
  implement `DataSourceStreamReader` and nothing else. There is **no `DataSourceStreamWriter`
  hook** — if your source needs a post-commit acknowledge or delete (a queue you must ack, a
  message you must remove), you cannot do it here the way a standalone Structured Streaming job
  can. `[repo]`
- **Runtime floor:** custom PySpark Data Sources need **DBR 15.4 LTS+** or serverless v2. `[docs]`
- **A full refresh resets every cursor.** It clears the checkpoint, which means all per-key offsets
  go back to `initialOffset()` — not just the table contents. That belongs in any backfill or
  replay plan, and it is the same hazard as
  [sdp-operations-and-refresh.md](./sdp-operations-and-refresh.md) → *a full refresh resets your
  position, not the world's history*, except multiplied by the number of keys.
- **Dynamic keys need a discovery path.** If the key set grows, `initialOffset()`/`partitions()`
  must find new keys as they appear. That discovery source has to be independent of the table this
  flow writes — a config table or a list endpoint, never the target.

## Bootstrapping from the target table

When the API cannot tell you its own newest offset, the starting point has to come from data
already landed. Deriving it inside `initialOffset()` works, and works for a precise reason: it is
**Python running outside the returned DataFrame's plan**, so the graph resolver never sees it. It is
the same mechanism as the lineage-severing trick in
[sdp-python-api.md](./sdp-python-api.md#severing-lineage-and-why-it-is-a-last-resort), but here it
is cheap and defensible rather than a last resort — `initialOffset()` is called only when there is
no checkpoint, so it is a first-run cost, not a per-trigger one.

```python
def _max_offsets(self):
    spark = SparkSession.getActiveSession()
    rows = (spark.table(self.target_table)
            .groupBy("iso", "name").agg(F.max("offset").alias("max_offset"))
            .collect())
    return {f"{r.iso}|{r.name}": r.max_offset for r in rows}

def initialOffset(self):
    existing = self._max_offsets()
    return {f"{iso}|{name}": existing.get(f"{iso}|{name}", 0) for iso, name in self.keys}
```

Two decisions around it:

- **Bootstrap only, or every trigger?** Bootstrap-only is the default: the checkpoint tracks
  progress after the first run. Re-deriving in `latestOffset()` too is *safe* — Delta snapshot
  isolation means the read sees the last committed version, never a partial write, so there is no
  race with the concurrent append — but it costs a `groupBy(keys).max(offset)` scan every trigger.
  Choose it only when the table must be the authority regardless of checkpoint state. `[deduced]`
- **Cluster the target by the cursor keys** so that aggregate is a file-stats lookup rather than a
  growing scan. Note the interaction in
  [sdp-operations-and-refresh.md](./sdp-operations-and-refresh.md) → clustering triggers compaction,
  which changes what a downstream `maxFilesPerTrigger` can do.

Guard the table's existence with the `information_schema` query from
[sdp-python-api.md](./sdp-python-api.md), not `spark.catalog.tableExists()`, which is unavailable
inside a pipeline.

## The gap a success-filtered high-water mark leaves

The source project resumed from `max(offset) WHERE request_success`, and left this as a TODO that
never got closed. It is worth stating as a rule, because the failure is silent and permanent:

> **A success-filtered high-water mark skips a failed middle window forever.** Concurrent pagination
> finishes window 3 and window 5 but fails window 4. The mark advances past 5. Window 4 is never
> retried, and no later run can notice, because the only state is a maximum.

If strict completeness matters, the cursor cannot be a single number per key. Track the windows you
have actually completed — a per-window row with a status, and resume from the lowest incomplete
window rather than the highest complete one. If it does not matter, write down that it does not,
next to the `max()`, so the next reader knows the gap is accepted rather than unnoticed.

## Sources

- Apache Spark — Python Data Source API: <https://spark.apache.org/docs/latest/api/python/tutorial/sql/python_data_source.html>
- Databricks — PySpark custom data sources: <https://learn.microsoft.com/en-us/azure/databricks/pyspark/datasources>

## Related

- [sdp-python-api.md](./sdp-python-api.md) — why reading the pipeline's own target is a cycle, and
  the three legitimate state patterns.
- [sdp-operations-and-refresh.md](./sdp-operations-and-refresh.md) — what a full refresh does to a
  checkpoint, and why it cannot recover what the source no longer offers.
- [develop-pyspark](../../develop-pyspark/SKILL.md) — the request envelope, retries and pagination
  inside `read()`.
