# Custom `FileFormat` DataSource in Scala

How to make Spark read a format it doesn't natively support (here: any document, via Apache Tika), so
`spark.read.format("mysource").load(path)` yields a DataFrame with a fixed schema.

## Extend `FileFormat` + `DataSourceRegister`

```scala
class TikaFileFormat extends FileFormat with DataSourceRegister {

  override def shortName(): String = "tika"            // the format("...") name

  override def inferSchema(spark: SparkSession, options: Map[String, String],
                           files: Seq[FileStatus]): Option[StructType] =
    Some(TikaSerializer.schema)                         // fixed output schema

  override def isSplitable(spark: SparkSession, options: Map[String, String], path: Path): Boolean =
    false                                               // a whole document can't be split

  override def prepareWrite(spark: SparkSession, job: Job, options: Map[String, String],
                            dataSchema: StructType): OutputWriterFactory =
    throw new UnsupportedOperationException("read-only") // no writer

  override def buildReader(spark: SparkSession, dataSchema: StructType, partitionSchema: StructType,
                           requiredSchema: StructType, filters: Seq[Filter],
                           options: Map[String, String],
                           hadoopConf: Configuration): PartitionedFile => Iterator[InternalRow] = {
    // 1) broadcast the Hadoop config so each task can open the filesystem
    val conf = spark.sparkContext.broadcast(new SerializableConfiguration(hadoopConf))
    // 2) capture typed options HERE (driver) and close over them — see build-options-testing.md
    val timeout = getOption(options, "timeout", 120)(_.toInt)

    (file: PartitionedFile) => {
      val path = new Path(file.filePath.toString)
      val fs = path.getFileSystem(conf.value.value)
      val status = fs.getFileStatus(path)
      val bytes = using(fs.open(path))(ByteStreams.toByteArray)   // whole file into memory
      try {
        val doc = parse(bytes, status, timeout)
        Iterator.single(TikaSerializer.serialize(doc, requiredSchema))
      } catch {
        case _: SkippableTikaException => Iterator.empty           // skip, don't fail the job
      }
    }
  }
}
```

Key points:
- Override `buildReader` (not `buildReaderWithPartitionValues`) unless you need partition-column
  values merged in.
- Broadcast a `SerializableConfiguration` — the raw Hadoop `Configuration` isn't serializable.
- Return `Iterator.single(row)` for one-row-per-file; `Iterator.empty` to **skip** a bad file
  without aborting the task; rethrow for genuinely fatal errors.
- `buildReader` returns a **closure**; capture driver-side config as vals so it serializes to tasks.

## Short-name registration (make `format("name")` work)

`DataSourceRegister.shortName` alone isn't enough — Spark discovers providers via a service file.
Create:

```
src/main/resources/META-INF/services/org.apache.spark.sql.sources.DataSourceRegister
```

containing the **fully-qualified class name**, e.g. `com.databricks.labs.tika.TikaFileFormat`.
The class's package, the service-file entry, and `shortName()` must all agree, or `format("tika")`
throws "failed to find data source". (The source repo drifted to `tika_alkv` in some places and
`tika` in others — reconcile all three.)

## Build the row: schema-driven `UnsafeRow`

Serialize a case class into Spark's internal row, **honouring the required (pruned/reordered)
schema** rather than the declared order:

```scala
case class ProcessedDocument(path: String, modificationTime: Long, length: Long,
                             content: Array[Byte], contentType: String,
                             contentText: String, contentMetadata: Map[String, String])

object TikaSerializer {
  val schema: StructType = StructType(Seq(
    StructField("path", StringType), StructField("modificationTime", TimestampType),
    StructField("length", LongType), StructField("content", BinaryType),
    StructField("contentType", StringType), StructField("contentText", StringType),
    StructField("contentMetadata", MapType(StringType, StringType))))

  def serialize(doc: ProcessedDocument, requiredSchema: StructType): UnsafeRow = {
    val writer = new UnsafeRowWriter(requiredSchema.length)
    writer.reset()
    requiredSchema.zipWithIndex.foreach { case (field, i) =>
      field.name match {
        case "path"        => writer.write(i, UTF8String.fromString(doc.path))
        case "length"      => writer.write(i, doc.length)
        case "content"     => writer.write(i, doc.content)
        case "contentText" => writer.write(i, UTF8String.fromString(doc.contentText))
        case "contentMetadata" => writeMap(writer, i, doc.contentMetadata)  // UnsafeArrayWriter
        // ... one case per field
      }
    }
    writer.getRow
  }
}
```

- Strings → `UTF8String.fromString`; maps → an unsafe map via `UnsafeArrayWriter` (keys + values).
- Iterating `requiredSchema` (not `schema`) is what makes **column pruning** correct — if Spark asks
  for only `contentText`, you must write only that column, at index 0.
- This is manual Catalyst serialization. The higher-level alternative (`Encoders.product[CaseClass]`
  / Dataset) is simpler but doesn't fit a `FileFormat` reader, which must emit `InternalRow`.

## Reading the file + Tika

- Read whole bytes with Guava `ByteStreams.toByteArray(fs.open(path))`; guard a max length.
- Tika: `new AutoDetectParser`, a `Metadata`, a `ParseContext` (configure PDF/Office/Tesseract
  parsers), and a `BodyContentHandler` (or `ToXMLContentHandler` for structured output). Call
  `parser.parse(stream, handler, metadata, parseContext)`, then read text + `metadata.names()` into a
  Scala `Map`. Set `TikaCoreProperties.RESOURCE_NAME_KEY` to the filename to help type detection, and
  close the stream in a `finally`.

## Tika gotchas: MIME detection, OCR, truncation

Non-obvious lessons from a Tika + Tesseract source (`tika-ocr`'s `TikaExtractor`):

- **Set the filename before detection or DOCX is misread as ZIP.** OOXML formats (`.docx`, `.xlsx`)
  are ZIP containers; detection from bytes alone often resolves them to `application/zip`. Add the
  name — `metadata.add(TikaCoreProperties.RESOURCE_NAME_KEY, filename)` — *before*
  `parser.getDetector.detect(stream, metadata)`. Detection is reliably better with a filename than
  from a bare stream.
- **OCR needs Tesseract installed natively on every executor.** Tika's `TesseractOCRConfig` only
  drives a native `tesseract` binary. If it's missing, parsing **does not fail** — it silently
  returns no text for image/scanned content. Install it in the cluster init script / container image
  on all executors, not just the driver.
- **Bound the OCR run:** `tesseractConfig.setTimeoutSeconds(n)` (the source defaults to 120) caps a
  per-document OCR; set it with the DataSource `timeout` option so one pathological scan can't hang a
  task.
- **`BodyContentHandler(writeLimit)` truncates at `writeLimit` chars** and throws past it;
  `new BodyContentHandler(-1)` is unlimited. A default-constructed handler silently truncates long
  documents at 100k chars — pass `-1` (or a deliberate cap) for whole-document extraction.
- Register the OCR/PDF/Office configs on the `ParseContext`
  (`parseContext.set(classOf[TesseractOCRConfig], cfg)`, etc.) *before* `parser.parse`.
