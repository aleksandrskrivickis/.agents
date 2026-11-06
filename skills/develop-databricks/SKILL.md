---
name: develop-databricks
description: 'Use when you work with the Databricks platform itself rather than authoring a pipeline — Unity Catalog introspection through system.information_schema, migrating Hive metastore tables with SYNC, the CREATE TABLE IF NOT EXISTS copy-versus-refresh trap, Delta time travel, creating a catalog on a managed location and granting, probing your privileges, connecting external sources (Neo4j, Azure SQL, Cosmos DB, legacy ADLS/Blob mounts), copying files and notebooks, secret scopes and injecting a secret into a cluster, enabling Databricks Container Services, logging and serving a custom MLflow model, calling Azure OpenAI from a notebook, and administering a Lakebase project. Defers pipeline authoring, transform internals, deployment and Azure infrastructure to the related skills.'
---

# Working with the Databricks platform

> **What this is.** The platform-usage layer around a Databricks project: the work you do *beside* a
> pipeline, not inside one. The core is reading Unity Catalog's own metadata and moving and
> versioning tables (below). The reference files extend it to cluster setup, credentials, external
> sources, file and notebook copying, model serving, LLM calls and Lakebase. It does **not** cover
> writing pipelines (see [develop-sdp](../develop-sdp/SKILL.md)), transform internals (see
> [develop-pyspark](../develop-pyspark/SKILL.md)), deployment (see
> [databricks-asset-bundles](../databricks-asset-bundles/SKILL.md)), or provisioning the workspace
> and catalog (see [develop-infrastructure](../develop-infrastructure/SKILL.md)). Distilled from
> production Databricks projects; every example uses invented catalog and table names.

## Detailed references

**Unity Catalog and tables**

- [references/unity-catalog-introspection.md](./references/unity-catalog-introspection.md) — the two
  information schemas, privilege-aware filtering, the view catalog, the lowercase/filter/`REPAIR`
  performance notes, and worked inventory queries.
- [references/table-migration-and-lifecycle.md](./references/table-migration-and-lifecycle.md) —
  `SYNC` in depth (external vs managed, the source write, status codes, the non-ASCII comment trap),
  `DEEP` vs `SHALLOW CLONE`, and time-travel retention with the `RESTORE` streaming caveat.
- [references/catalog-administration.md](./references/catalog-administration.md) — create a catalog
  on a managed location and grant, snapshot a whole schema, and bulk-migrate a Hive schema.
- [references/test-queries.md](./references/test-queries.md) — Delta time travel, a combined
  catalog inventory query, and a destructive privilege probe.

**Connecting and moving data**

- [references/external-sources.md](./references/external-sources.md) — Neo4j, Azure SQL (service
  principal), Cosmos DB merged into Delta, and legacy ADLS/Blob mounts.
- [references/file-operations.md](./references/file-operations.md) — copy files with shell, copy a
  notebook with the Workspace export/import API.

**Compute, credentials and serving**

- [references/cluster-configuration.md](./references/cluster-configuration.md) — enable Databricks
  Container Services, and inject a secret as a Spark config or environment variable.
- [references/credential-management.md](./references/credential-management.md) — secret scopes,
  put/get/ACL, redaction, and Key Vault-backed scopes.
- [references/model-serving.md](./references/model-serving.md) — log a custom MLflow `pyfunc` with a
  typed signature, register it, and call the serving endpoint.
- [references/llm-analysis.md](./references/llm-analysis.md) — call Azure OpenAI with LangChain from
  secrets, count tokens, and drive a structured prompt.
- [references/lakebase.md](./references/lakebase.md) — administer a Lakebase (managed Postgres)
  project through the SDK raw API client.

**Deployment**

- [references/asset-bundles.md](./references/asset-bundles.md) — a minimal bundle scaffold; a pointer
  into the [databricks-asset-bundles](../databricks-asset-bundles/SKILL.md) skill.

## Unity Catalog introspection

Unity Catalog describes itself in the read-only `system.information_schema` schema. Query it to list
catalogs, schemas, tables and grants, instead of clicking through the UI.

```sql
-- Catalogs you can see, their owners, and how many schemas each holds
SELECT c.catalog_name, c.catalog_owner, COUNT(s.schema_name) AS schemas
FROM system.information_schema.catalogs AS c
LEFT JOIN system.information_schema.schemata AS s USING (catalog_name)
GROUP BY c.catalog_name, c.catalog_owner;

-- Who holds which privilege on one catalog
SELECT grantee, privilege_type, is_grantable
FROM system.information_schema.catalog_privileges
WHERE catalog_name = 'my_catalog';
```

Three traps make an inventory wrong or slow without an error:

- **It shows only what the caller can see.** `information_schema` is filtered by the running
  identity's grants, so a run as a low-privilege user is silently partial. Run it as a metastore
  admin for a complete picture.
- **It excludes the legacy Hive metastore.** Tables under `hive_metastore` never appear here. List
  those with `SHOW TABLES IN hive_metastore.<schema>`.
- **Match lowercase, and filter.** Identifiers are stored lowercase, so compare them directly and do
  not wrap a column in `LOWER()`. Filter by `table_catalog` and `table_schema`, because `LIMIT` is
  not pushed down and a broad scan can time out.

→ Deeper: [references/unity-catalog-introspection.md](./references/unity-catalog-introspection.md).

## Migrating Hive metastore tables into Unity Catalog

`SYNC` upgrades a Hive metastore table, or a whole schema, to a Unity Catalog target. It is
idempotent and copies the metadata, not the data.

```sql
SYNC TABLE main.default.customers FROM hive_metastore.default.customers DRY RUN;
SYNC TABLE main.default.customers FROM hive_metastore.default.customers;
SYNC SCHEMA main.default FROM hive_metastore.default;
```

Run `DRY RUN` first to see what it would change. `SYNC` upgrades **external** tables only; copy a
managed Hive table with `CREATE TABLE main.default.customers DEEP CLONE hive_metastore.default.customers`.

## The copy-versus-refresh trap

`CREATE TABLE IF NOT EXISTS <t> AS SELECT …` is **not** a refresh. If the target already exists, the
statement is a no-op: the `SELECT` never runs and the data never updates. A nightly job built this
way looks healthy and serves stale data forever.

Choose the statement that matches your intent:

- **Create once, never overwrite** → `CREATE TABLE IF NOT EXISTS … AS SELECT …`.
- **Replace the whole table each run** → `CREATE OR REPLACE TABLE … AS SELECT …`.
- **Upsert rows** → `MERGE INTO … USING … ON … WHEN MATCHED … WHEN NOT MATCHED …`.

## Delta time travel

Every Delta table keeps a version history. Use it to audit a change or to roll back.

```sql
DESCRIBE HISTORY main.default.customers;               -- versions, operations, who and when
SELECT * FROM main.default.customers VERSION AS OF 42;
SELECT * FROM main.default.customers TIMESTAMP AS OF '2026-01-01';
RESTORE TABLE main.default.customers TO VERSION AS OF 42;
```

History is bounded by retention. `VACUUM` and the `delta.logRetentionDuration` and
`delta.deletedFileRetentionDuration` settings decide how far back you can travel. Do not promise a
rollback to a version older than the retention window.

→ Deeper: [references/table-migration-and-lifecycle.md](./references/table-migration-and-lifecycle.md) — `SYNC` status codes, cloning, and the `RESTORE` streaming caveat.

## The rules that prevent most platform mistakes

- Run an inventory query as a **metastore admin**, or accept that it is partial.
- Never trust `CREATE TABLE IF NOT EXISTS … AS SELECT` to refresh data. Use `OR REPLACE` or `MERGE`.
- `SYNC … DRY RUN` before a real `SYNC`; it upgrades external tables only.
- Check `DESCRIBE HISTORY` retention before you promise a rollback point.

## Quick symptom → fix index

| Symptom | What it means | Fix |
|---|---|---|
| An inventory query misses tables | The caller lacks grants, or the tables live in `hive_metastore` | Run as a metastore admin; query `hive_metastore` separately |
| A nightly CTAS serves stale data | `IF NOT EXISTS` skipped the existing target | Switch to `CREATE OR REPLACE` or `MERGE` |
| `SYNC` reports nothing to do | The source is a managed, not external, table | Use `CREATE TABLE … DEEP CLONE …` instead |
| `VERSION AS OF` fails for an old version | The version fell outside the retention window | Raise `delta.logRetentionDuration`; stop relying on vacuumed history |

## Commands

```sql
SELECT * FROM system.information_schema.tables WHERE table_schema = 'default';
SYNC SCHEMA main.default FROM hive_metastore.default DRY RUN;
DESCRIBE HISTORY main.default.customers;
RESTORE TABLE main.default.customers TO VERSION AS OF 42;
```

## Upstream documentation (sources)

- Unity Catalog `information_schema`: https://docs.databricks.com/en/sql/language-manual/sql-ref-information-schema.html
- `SYNC` command: https://docs.databricks.com/en/sql/language-manual/sql-ref-syntax-aux-sync.html
- Delta time travel and history: https://docs.databricks.com/en/delta/history.html
- `MERGE INTO`: https://docs.databricks.com/en/sql/language-manual/delta-merge-into.html

## When to use this skill

Use it when you administer or inspect a Databricks workspace's data — catalogs, schemas, tables and
their history — or when you report on data coverage. Use it also for the day-to-day platform tasks in
the references: configuring a cluster, managing secrets, connecting an external source, copying files
or notebooks, serving a model, calling an LLM, or administering Lakebase. To build the pipelines that
fill those tables, use the related skills.

## Related skills

- [develop-sdp](../develop-sdp/SKILL.md) — authoring the pipelines that write these tables.
- [develop-pyspark](../develop-pyspark/SKILL.md) — the transform internals inside those pipelines.
- [databricks-asset-bundles](../databricks-asset-bundles/SKILL.md) — deploying jobs, pipelines and
  catalog resources.
- [develop-infrastructure](../develop-infrastructure/SKILL.md) — provisioning the workspace, storage
  and Unity Catalog these tables live in.
