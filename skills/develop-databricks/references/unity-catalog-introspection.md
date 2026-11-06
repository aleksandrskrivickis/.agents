# Unity Catalog introspection in depth

> **Source.** The Databricks "Information schema" reference, verified against the live docs on
> 2026-11-06. Confidence tags: `[docs]` a documented behaviour, `[deduced]` an inference, `[?]`
> worth verifying.

## Two information schemas `[docs]`

Unity Catalog exposes catalog metadata through SQL in two places:

- **`system.information_schema`** — metastore-wide. It describes objects across **all** catalogs, and
  it **does not** contain `hive_metastore` objects. Use it for a whole-metastore inventory.
- **`<catalog>.information_schema`** — one per catalog, describing that catalog only. Use it when you
  work inside a single catalog.

Both are **privilege-aware**: they filter automatically to the objects your identity can access, and
they need **no explicit `SELECT` grant**. If your grants change, the rows you see change. A run as a
low-privilege user is therefore silently partial. Run a full inventory as a metastore admin.

## The views you will use most `[docs]`

| View | What it lists |
|---|---|
| `catalogs` | Catalogs, with `catalog_owner` |
| `schemata` | Schemas, with `catalog_name` and `schema_owner` |
| `tables` | Tables and views, with `table_owner`, `created`, `last_altered` |
| `columns` | Columns, with `data_type` |
| `catalog_privileges` / `schema_privileges` / `table_privileges` | Which principal holds which grant |
| `routines` | Functions |
| `volumes` | Unity Catalog volumes |

## Performance and correctness notes `[docs]`

- **Identifiers are stored lowercase.** Compare them directly. Do not wrap a column in `LOWER()` or
  `UPPER()`.
- **Filter early.** Add `WHERE table_catalog = '…' AND table_schema = '…'`. A broad query over a
  large metastore can time out.
- **`LIMIT` is not pushed down.** It truncates the result but does not speed the scan.
- **A metadata change can lag.** After some catalog changes, run `REPAIR TABLE` to refresh what the
  information schema reports.

## Worked inventory queries

```sql
-- Tables created or altered in the last day
SELECT table_catalog, table_schema, table_name, table_owner, last_altered
FROM system.information_schema.tables
WHERE datediff(now(), last_altered) < 1;

-- Table count per schema in one catalog
SELECT table_schema, COUNT(table_name) AS tables
FROM system.information_schema.tables
WHERE table_catalog = 'main'
GROUP BY table_schema
ORDER BY tables DESC;

-- Every principal that can read a catalog
SELECT grantee, privilege_type
FROM system.information_schema.catalog_privileges
WHERE catalog_name = 'main';
```
