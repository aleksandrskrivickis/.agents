# Test queries

> **What this is.** Two diagnostics: Delta time travel, and a Unity Catalog inventory plus a
> privilege probe. From Databricks example notebooks; catalog, schema and table names are obfuscated.

## Delta time travel

```sql
DESCRIBE HISTORY main.default.my_table;
SELECT * FROM main.default.my_table VERSION AS OF 28;
```

See [table-migration-and-lifecycle](./table-migration-and-lifecycle.md) for retention limits and
`RESTORE`.

## Inventory catalogs from `information_schema`

Owners, grantees, privileges and schema counts in one query:

```sql
SELECT
    c.catalog_name,
    c.catalog_owner,
    collect_set(cp.grantee)        AS grantees,
    collect_set(cp.privilege_type) AS privilege_types,
    MAX(sc.schema_count)           AS schema_count
FROM system.information_schema.catalogs c
LEFT JOIN system.information_schema.catalog_privileges cp
    ON c.catalog_name = cp.catalog_name
LEFT JOIN (
    SELECT catalog_name, COUNT(DISTINCT schema_name) AS schema_count
    FROM system.information_schema.schemata
    GROUP BY catalog_name
) sc ON c.catalog_name = sc.catalog_name
GROUP BY c.catalog_name, c.catalog_owner
ORDER BY c.catalog_name;
```

## Probe your privileges on a catalog

This loop runs the whole DDL/DML lifecycle and reports which step your identity is allowed to do. It
ends with `DROP SCHEMA … CASCADE`, so it is **destructive** — run it only against a throwaway
catalog.

```python
test_catalog = f"`{spark.catalog.currentCatalog()}_probe`"
test_schema = "capability_test"
test_table = "test_records"
schema_fqn = f"{test_catalog}.{test_schema}"
table_fqn = f"{test_catalog}.{test_schema}.{test_table}"

steps = [
    ("Create schema", f"CREATE SCHEMA {schema_fqn}"),
    ("Create table", f"CREATE TABLE {table_fqn} (id INT, name STRING) USING DELTA"),
    ("Insert records", f"INSERT INTO {table_fqn} VALUES (1,'A'),(2,'B'),(3,'C')"),
    ("Select all", f"SELECT * FROM {table_fqn}"),
    ("Filtered select", f"SELECT * FROM {table_fqn} WHERE id > 1"),
    ("Update record", f"UPDATE {table_fqn} SET name='A-updated' WHERE id=1"),
    ("Delete record", f"DELETE FROM {table_fqn} WHERE id=3"),
    ("Drop table", f"DROP TABLE {table_fqn}"),
    ("Drop schema", f"DROP SCHEMA {schema_fqn} CASCADE"),
]

results = []
for op, sql in steps:
    try:
        out = spark.sql(sql).limit(5).toPandas().to_json()
        results.append((op, "SUCCESS", str(out)))
    except Exception as e:
        results.append((op, "FAILED", str(e)[:150]))

spark.createDataFrame(results, ["operation", "status", "outcome"]).display()
```
