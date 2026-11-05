---
name: develop-scala
description: 'Use when writing Scala for Spark / Databricks — especially a custom FileFormat DataSource (buildReader, inferSchema, isSplitable, DataSourceRegister/shortName + META-INF/services), schema-driven UnsafeRow construction honouring required-column pruning, typed DataSource option parsing with defaults, a scoped mutable-config loan pattern, Tika document extraction, and Maven shaded packaging with Spark as provided scope + ScalaTest against a local SparkSession. Distilled from a custom Tika Spark DataSource.'
---

# Scala on Spark / Databricks

> **What this is.** Patterns from a custom **Apache Tika Spark DataSource** — a reader that pulls
> arbitrary documents (PDF, Office, HTML) into a DataFrame. The valuable material here is
> **low-level Catalyst / DataSource** work: things the Python API cannot express at all, where you
> are writing against Spark's implementation-level interfaces rather than its stable public API.
>
> If you only need to *read* documents into Spark, you probably don't need this — see
> [file-and-document-ingestion](../develop-pyspark/references/file-and-document-ingestion.md) for the
> Python options first. Reach for a custom DataSource when the format genuinely has no reader and you
> need Spark-native pruning and partitioning.

## Detailed references

- [references/custom-fileformat-datasource.md](./references/custom-fileformat-datasource.md) — implementing a `FileFormat`, short-name registration, and `UnsafeRow` serialization.
- [references/build-options-testing.md](./references/build-options-testing.md) — typed options, the scoped-config loan pattern, Maven/shade packaging, ScalaTest with a local SparkSession.

## The rules that keep a Scala Spark extension working

1. **These are internal APIs — pin the Spark version.** `FileFormat`, `PartitionedFile`,
   `InternalRow`, `UnsafeRow`, `UnsafeRowWriter`/`UnsafeArrayWriter` are **implementation-level**,
   not the stable DataFrame API. They change across Spark *minor* versions. Pin to the target
   Databricks Runtime's exact Spark version, and rebuild on every runtime upgrade — a working jar is
   not evidence that the next runtime will load it.
2. **Keep registration consistent across three places**, or `spark.read.format("name")` fails with a
   confusing "failed to find data source":
   - the `override def shortName()` string,
   - the class named in `META-INF/services/org.apache.spark.sql.sources.DataSourceRegister`,
   - the actual package/class path.

   The source project had these out of sync (`tika_alkv` vs `tika`) — a real bug, and one that only
   shows up at read time, never at build time.
3. **Honour `requiredSchema`, not the declared schema**, when building rows. Spark prunes and
   reorders columns, so iterate `requiredSchema.zipWithIndex` and write by field. Build against the
   declared schema and a query selecting two columns silently gets the wrong two.
4. **Spark is `provided` scope.** Never bundle Spark into your jar. Shade only *your* dependencies,
   and use the Maven Shade `ServicesResourceTransformer` so the `META-INF/services` provider file
   survives the shade — without it, rule 2 is satisfied in your source tree and broken in your
   artifact.
5. **A loan pattern around a static/global setting is not concurrency-safe.** Scoping a system
   property or an Apache POI global with `try/finally` works per JVM, but multiple tasks in one
   executor JVM share it. Fine for per-JVM configuration; a race per task.

## The five DataSource lifecycle methods

| Method | Role |
|---|---|
| `shortName(): String` | the `format("...")` name (from `DataSourceRegister`) |
| `inferSchema(...): Option[StructType]` | fixed output schema — return `Some(mySchema)` |
| `isSplitable(...): Boolean` | `false` for whole-file formats (a document can't be split) |
| `buildReader(...): PartitionedFile => Iterator[InternalRow]` | the reader: bytes → row(s) |
| `prepareWrite(...)` | throw `UnsupportedOperationException` for a read-only source |

## When to use this skill

- Writing a **custom Spark data source / file format** in Scala, for a binary or document format
  Spark cannot read natively.
- Working at the Catalyst level (`InternalRow`, `UnsafeRow`, `StructType`), or packaging a Spark
  extension jar.
- Typed Scala Spark — case classes, options parsing, loan-pattern resource scoping — and testing it
  against a local `SparkSession`.

## Related skills

- [develop-pyspark](../develop-pyspark/SKILL.md) — the Python side, including
  [document ingestion](../develop-pyspark/references/file-and-document-ingestion.md) via
  `binaryFile` and Auto Loader, which is the right first choice for most document reading.
- [test-python](../test-python/SKILL.md) — for the local-SparkSession fixture pattern, which
  translates closely to ScalaTest.
