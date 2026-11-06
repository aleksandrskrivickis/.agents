# Catalog administration

> **What this is.** Three admin patterns: create a catalog on a managed location, snapshot a whole
> schema, and bulk-migrate Hive tables into Unity Catalog. From Databricks example notebooks; storage
> accounts, catalog and schema names are obfuscated.

## Create a catalog on a managed location, then grant

```sql
CREATE CATALOG IF NOT EXISTS my_catalog
  MANAGED LOCATION 'abfss://<container>@<storage-account>.dfs.core.windows.net/depts/finance';

GRANT SELECT ON CATALOG my_catalog TO `finance-team`;
```

Use the `abfss://` (ADLS Gen2) scheme; the older `wasbs://` (Blob) form works but prefer ADLS Gen2.

## Snapshot a whole schema (copy every table)

Loop over `SHOW TABLES`, then `CREATE TABLE IF NOT EXISTS … AS SELECT` into a snapshot schema.

```python
from tqdm import tqdm
import traceback

source_catalog, source_schema = "main", "my_schema"
target_catalog, target_schema = "main", "my_schema_snapshot"

tables = (
    spark.sql(f"SHOW TABLES IN {source_catalog}.{source_schema}")
    .filter("isTemporary = false")
    .select("tableName")
    .collect()
)

spark.sql(f"CREATE SCHEMA IF NOT EXISTS {target_catalog}.{target_schema}")

for t in tqdm(tables, total=len(tables)):
    table = t.tableName
    try:
        spark.sql(f"""
            CREATE TABLE IF NOT EXISTS {target_catalog}.{target_schema}.{table}
            AS SELECT * FROM {source_catalog}.{source_schema}.{table}
        """)
    except Exception:
        traceback.print_exc()
```

> `IF NOT EXISTS` **skips** an existing target, so this is a one-shot snapshot, not a refresh. To
> refresh, use `CREATE OR REPLACE` or `MERGE` — see the copy-versus-refresh trap in
> [the skill overview](../SKILL.md).

## Bulk-migrate Hive tables into Unity Catalog

Loop `SYNC TABLE` over a Hive schema, collect the per-table status rows, union them into one report.

```python
from tqdm import tqdm
import traceback

source_catalog, source_schema = "hive_metastore", "my_schema"
target_catalog, target_schema = "main", "my_schema"

tables = (
    spark.sql(f"SHOW TABLES IN {source_catalog}.{source_schema}")
    .filter("isTemporary = false")
    .select("tableName")
    .collect()
)

results = []
for t in tqdm(tables, total=len(tables)):
    table = t.tableName
    try:
        results.append(
            spark.sql(
                f"SYNC TABLE {target_catalog}.{target_schema}.{table} FROM {source_catalog}.{source_schema}.{table}"
            )
        )
    except Exception:
        print(f"Skipping {target_catalog}.{target_schema}.{table}")
        traceback.print_exc()

status = results[0]
for r in results[1:]:
    status = status.union(r)
display(status)
```

`SYNC` upgrades external tables only; for status codes and the managed-table path see
[table-migration-and-lifecycle](./table-migration-and-lifecycle.md).
