---
name: develop-scala
description: 'Use when writing Scala for Spark / Databricks \u2014 especially a custom FileFormat DataSource (buildReader, inferSchema, isSplitable, DataSourceRegister/shortName + META-INF/services), schema-driven UnsafeRow construction honouring required-column pruning, typed DataSource option parsing with defaults, a scoped mutable-config loan pattern, Tika document extraction, and Maven shaded packaging with Spark as provided scope + ScalaTest against a local SparkSession. Distilled from a custom Tika Spark DataSource (databricks-ingestion-pipeline-scala).'
---

# Scala on Spark / Databricks

Patterns distilled from a custom **Apache Tika Spark DataSource** (reads arbitrary documents into a
DataFrame). The high-value material is **low-level Catalyst / DataSource** work, which the Python API
can't express. References:

- [references/custom-fileformat-datasource.md](./references/custom-fileformat-datasource.md) \u2014 implementing a `FileFormat`, short-name registration, and `UnsafeRow` serialization.
- [references/build-options-testing.md](./references/build-options-testing.md) \u2014 typed options, the scoped-config loan pattern, Maven/shade packaging, ScalaTest with a local SparkSession.

## When to use

- Writing a **custom Spark data source / file format** in Scala (e.g. read a binary/document format
  Spark can't natively).
- Working at the Catalyst level (`InternalRow`, `UnsafeRow`, `StructType`), or packaging a Spark
  extension jar.
- Typed Scala Spark (case classes, options parsing, loan-pattern resource scoping) and testing it.

## The rules that keep a Scala Spark extension working

1. **Internal APIs \u2014 pin the Spark version.** `FileFormat`, `PartitionedFile`, `InternalRow`,
   `UnsafeRow`, `UnsafeRowWriter`/`UnsafeArrayWriter` are **implementation-level**, not the stable
   DataFrame API. They change across Spark minors. Pin to the target Databricks Runtime's exact Spark
   version and rebuild on upgrade.
2. **Keep registration consistent across three places** or `spark.read.format("name")` fails: the
   `override def shortName()` string, the class named in
   `META-INF/services/org.apache.spark.sql.sources.DataSourceRegister`, and the actual package/class
   path. (The source repo has these three out of sync \u2014 `tika_alkv` vs `tika` \u2014 a real bug to avoid.)
3. **Honour `requiredSchema`, not the declared schema**, when building rows \u2014 Spark prunes/reorders
   columns, so iterate `requiredSchema.zipWithIndex` and write by field, or you return wrong columns.
4. **Spark is `provided` scope.** Never bundle Spark into your jar; shade only *your* deps, and use
   the Maven Shade `ServicesResourceTransformer` so the `META-INF/services` provider file survives.
5. **Scoping a static/global setting (Apache POI, system props) via a loan pattern is not
   concurrency-safe** \u2014 multiple tasks in one executor JVM share it. Fine for per-JVM config, risky
   per-task.

## The five DataSource lifecycle methods (quick reference)

| Method | Role |
|---|---|
| `shortName(): String` | the `format("...")` name (from `DataSourceRegister`) |
| `inferSchema(...): Option[StructType]` | fixed output schema \u2014 return `Some(mySchema)` |
| `isSplitable(...): Boolean` | `false` for whole-file formats (a document can't be split) |
| `buildReader(...): PartitionedFile => Iterator[InternalRow]` | the reader: bytes \u2192 row(s) |
| `prepareWrite(...)` | throw `UnsupportedOperationException` for a read-only source |
