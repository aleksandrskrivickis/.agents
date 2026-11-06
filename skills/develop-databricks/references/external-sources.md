# External sources

> **What this is.** Reading external systems into Spark on Databricks, one connector per section.
> From Databricks example notebooks; every credential, endpoint and identifier below is a
> placeholder, and secrets are read from a secret scope — see
> [credential-management](./credential-management.md).

## Neo4j

Requires the **Neo4j Connector for Apache Spark** (`org.neo4j:neo4j-connector-apache-spark_2.12`).

```python
df = (
    spark.read.format("org.neo4j.spark.DataSource")
    .option("url", "neo4j+s://<your-db>.databases.neo4j.io")
    .option("authentication.type", "basic")
    .option("authentication.basic.username", dbutils.secrets.get("neo4j", "username"))
    .option("authentication.basic.password", dbutils.secrets.get("neo4j", "password"))
    .option("labels", "Tweet")  # or .option("query", "MATCH (n:Tweet) RETURN n LIMIT 100")
    .load()
)
display(df)
```

Use `neo4j+s://` (TLS) for a managed instance; `bolt://host:7687` for a direct connection. To write
back, use `.mode("Overwrite")` with `.option("labels", ":Person")` and `.option("node.keys", "id")`.

## Azure SQL (service principal)

Requires the Microsoft JDBC driver (bundled on most runtimes) and an Entra ID service principal.

```python
tenant_id = dbutils.secrets.get("sql", "tenant-id")
client_id = dbutils.secrets.get("sql", "client-id")
client_secret = dbutils.secrets.get("sql", "client-secret")

df = (
    spark.read.format("jdbc")
    .option("url", "jdbc:sqlserver://<server>.<region>.database.windows.net:1433")
    .option("database", "<database>")
    .option("dbtable", "INFORMATION_SCHEMA.SCHEMATA")
    .option("authentication", "ActiveDirectoryServicePrincipal")
    .option("user", client_id)  # client id, not a SQL login
    .option("password", client_secret)
    .option("aadTenantId", tenant_id)
    .option("encrypt", "true")  # required by Azure SQL
    .load()
)
df.limit(10).display()
```

## Cosmos DB → merge into Delta

Requires the Cosmos Spark connector (`com.azure.cosmos.spark:azure-cosmos-spark_3-3_2-12:<version>`).

```python
from pyspark.sql.functions import col

source = (
    spark.read.format("cosmos.oltp")
    .options(
        **{
            "spark.cosmos.accountEndpoint": dbutils.secrets.get("<kv-scope>", "cosmos-endpoint"),
            "spark.cosmos.accountKey": dbutils.secrets.get("<kv-scope>", "cosmos-key"),
            "spark.cosmos.database": "<database>",
            "spark.cosmos.container": "<container>",
        }
    )
    .load()
    .withColumn("ingestedAt", col("current_timestamp"))
)
```

```python
from delta.tables import DeltaTable

target = DeltaTable.forName(spark, "main.external.cosmos_items")
(target.alias("t").merge(source.alias("s"), "s.id = t.id").whenMatchedUpdateAll().whenNotMatchedInsertAll().execute())
```

> The original example ran `CREATE CATALOG IF NOT EXISTS {table}` — a bug that creates a *catalog*
> named after the table. Create the **schema** then the table. Deduplicate the source on `id` first,
> or `MERGE` raises a multiple-match error.

## Mount ADLS Gen2 / Blob (legacy)

**Prefer a Unity Catalog external location** — see
[develop-infrastructure](../../develop-infrastructure/SKILL.md). Mounts are a legacy,
workspace-wide pattern kept for reference.

```python
storage_account = "<storage-account>"
access_key = dbutils.secrets.get("<kv-scope>", "storage-access-key")
container = "ingestion"
mount_point = "/mnt/ingestion/"

if not any(m.mountPoint == mount_point for m in dbutils.fs.mounts()):
    dbutils.fs.mount(
        source=f"wasbs://{container}@{storage_account}.blob.core.windows.net",
        mount_point=mount_point,
        extra_configs={f"fs.azure.account.key.{storage_account}.blob.core.windows.net": access_key},
    )
display(dbutils.fs.ls(mount_point))
```

An account key grants full access to the whole account. Prefer a Unity Catalog storage credential
and external location, which scope access per container and per grant.
