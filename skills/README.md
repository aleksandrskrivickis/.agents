# Skills

Each skill in this handbook is a self-contained chapter on one engineering surface: a lean
`SKILL.md` you can read end to end, plus `references/` files carrying the detail. They were written
as working context for coding agents, which is why they are shaped the way they are — **problem →
cause → fix**, with the failure named before the remedy, and with the reasoning behind a value kept
next to the value.

That shape turns out to serve a human reader too. If you are here to learn rather than to fix
something, read a skill's **rules** section first: it is the condensed form of what the rest of the
chapter argues for.

## How a chapter is organised

- **Opening note** — what the subject is, where the knowledge came from, and what it does not cover.
- **Detailed references** — the deep material, one file per topic.
- **Rules** — the handful of things that prevent most of the failures in this area.
- **Symptom → fix index** — a lookup for when something is already broken.
- **Commands** — the commands worth memorising.
- **When to use / Related skills** — where the boundaries are.

Reference files open with a **Source** note stating where their claims come from. Where a claim is
inferred rather than observed it is tagged inline — `[repo]` for confirmed in code, `[docs]` for a
vendor-documented constraint, `[deduced]` for an inference, `[?]` for a guess worth verifying.

## The chapters

### Data pipelines on Databricks

- [develop-sdp](./develop-sdp/SKILL.md) — Spark Declarative Pipelines: the `pyspark.pipelines` API, streaming tables vs materialized views, flows, expectations, AUTO CDC, the event log, and which features are Apache SDP vs Databricks-only.
- [develop-pyspark](./develop-pyspark/SKILL.md) — PySpark under load: pandas/Arrow UDFs and OOM, Arrow conversion failures, model serving, chunking and embeddings, stateful streaming, joins and skew, throughput, reliable API calls, file ingestion.
- [develop-scala](./develop-scala/SKILL.md) — Scala on Spark: a custom `FileFormat` DataSource, `UnsafeRow` construction, Maven shading, ScalaTest.

### Deployment and infrastructure

- [databricks-asset-bundles](./databricks-asset-bundles/SKILL.md) — `databricks.yml`: targets and deployment modes, variables and interpolation, resource types, Lakebase, post-deploy runs, and the deploy-time gotchas.
- [develop-infrastructure](./develop-infrastructure/SKILL.md) — the Azure platform underneath: Bicep at subscription scope, Terraform for Unity Catalog, and the Azure DevOps pipelines that orchestrate both.

### Testing and CI

- [test-python](./test-python/SKILL.md) — pytest layout, testing non-importable notebook modules, local-Spark fixtures, bundle and wheel tests, integration and golden-corpus testing.
- [test-workflows-github](./test-workflows-github/SKILL.md) — a GitHub Actions lint-and-test pipeline, and how merges actually get gated.
- [test-workflows-devops](./test-workflows-devops/SKILL.md) — the Azure DevOps equivalent, including the Azure Repos `pr:` trigger trap.

### Engineering practice

- [document-decisions](./document-decisions/SKILL.md) — how to write down the constants, thresholds and algorithm choices a system is built on, so "nobody knows why this is 0.8" stops being true.

## Reading order, if you are starting cold

1. **[document-decisions](./document-decisions/SKILL.md)** — it is the shortest, and it explains why
   the other chapters keep rationale next to values.
2. **[develop-sdp](./develop-sdp/SKILL.md)** then **[develop-pyspark](./develop-pyspark/SKILL.md)** —
   the declarative layer, then what goes wrong inside it.
3. **[databricks-asset-bundles](./databricks-asset-bundles/SKILL.md)** then
   **[develop-infrastructure](./develop-infrastructure/SKILL.md)** — how the work gets deployed, then
   what it gets deployed onto.
4. **[test-python](./test-python/SKILL.md)** — and whichever CI chapter matches your host.
