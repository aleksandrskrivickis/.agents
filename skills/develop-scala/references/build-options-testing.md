# Options, scoped config, build & testing (Scala Spark)

## Typed DataSource options with defaults

DataSource options arrive as `Map[String, String]`. Parse to typed values with a default and turn a
bad value into a clear `SparkException`:

```scala
def getOption[T](options: Map[String, String], key: String, default: T)(parse: String => T): T =
  options.get(key).map(v => Try(parse(v)).getOrElse(
    throw new SparkException(s"Invalid value for option '$key': $v"))).getOrElse(default)

// use in buildReader (driver side), then close over the result:
val timeout        = getOption(options, "timeout", 120)(_.toInt)
val skipEncrypted  = getOption(options, "skipEncrypted", true)(_.toBoolean)
val writeLimit     = getOption(options, "writeLimit", -1)(_.toInt)
```

## Scoped mutable config (loan pattern)

To change a **global/static** library setting only around a block and always restore it:

```scala
class GenericConfigManager[T](setFunc: T => Unit, originalValue: T, newValue: T) {
  def apply[U](block: => U): U = {           // by-name block
    setFunc(newValue)
    try block finally setFunc(originalValue) // restore even on exception
  }
}

// e.g. widen Apache POI's byte-array limit just for this parse:
new GenericConfigManager[Int](IOUtils.setByteArrayMaxOverride, original, 300000000) {
  // ...parse here...
}
```

> ⚠️ This scopes a **process-global** setting. In Spark, many tasks share one executor JVM, so a
> static override (POI, system properties) is **not task-safe** — concurrent parses race on it. Fine
> for per-JVM init; risky per-task. Prefer passing config through the parser instance where possible.

## Build & packaging (Maven)

- Pin **Scala** (e.g. `2.12.15`, binary `2.12`), **Spark** (match the target Databricks Runtime,
  e.g. `3.5.0`), **Java** (`11`).
- Spark deps (`spark-sql_2.12`, `spark-core`, …) and the Scala library/reflect are **`provided`** —
  the runtime supplies them; bundling them causes conflicts.
- Shade only *your* dependencies (Tika, POI, …). The critical transformers:
  - `ServicesResourceTransformer` — **merges/preserves `META-INF/services`** so your
    `DataSourceRegister` entry survives (without it, `format("name")` silently stops resolving).
  - `ManifestResourceTransformer`; and exclude signature files (`*.SF/*.DSA/*.RSA`) to avoid
    "invalid signature" at load.
- Build a shaded jar: `mvn clean package -Pshaded`; install the jar as a cluster library.

```xml
<dependency>
  <groupId>org.apache.spark</groupId>
  <artifactId>spark-sql_${scala.binary.version}</artifactId>
  <version>${spark.version}</version>
  <scope>provided</scope>
</dependency>
```

## Testing with a local SparkSession (ScalaTest)

```scala
class TikaExtractorTest extends AnyFlatSpec with Matchers {
  lazy val spark = SparkSession.builder().appName("Tika").master("local[1]").getOrCreate()

  "the source" should "read a directory of documents" in {
    val df = spark.read.format("tika").load("src/test/resources/texts")
    df.count() should be (16)
    df.select("contentText").collect().head.getString(0) should include ("expected")
  }
}
```

- `master("local[1]")` for deterministic, single-threaded tests; `lazy val` so the session starts
  once.
- Unit-test the pure pieces directly: `UnsafeRow` field values and `UnsafeMapData` reconstruction,
  case-class equality, and that the scoped-config manager **restores** the original value and returns
  the block's result.
- Cover the DataSource edge cases: XML/HOCR options, unsupported write (expects the exception),
  max-length, invalid option value, and skip-vs-fail behaviour for encrypted/temp files.
