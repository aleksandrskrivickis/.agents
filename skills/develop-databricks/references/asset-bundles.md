# Asset bundles

> **What this is.** A minimal Databricks Asset Bundle (DAB) — a sample job and pipeline deployed with
> the Databricks CLI. The full treatment of bundles is the
> [databricks-asset-bundles](../../databricks-asset-bundles/SKILL.md) skill; this reference is just a
> runnable scaffold.

## Shape of a bundle

```
my-bundle/
├── databricks.yml                 # bundle name, targets (dev/prod), variables
├── resources/
│   ├── sample_job.job.yml         # a job definition
│   └── bundle_etl.pipeline.yml    # a pipeline definition
├── src/                           # the Python the job and pipeline run
└── tests/                         # pytest, with a conftest fixture
```

## Deploy it

```bash
databricks bundle validate            # catch schema and duplicate-key errors locally
databricks bundle deploy -t dev       # deploy to the dev target (name-prefixed in dev mode)
databricks bundle run sample_job -t dev
```

## Notes

- `bundle validate` catches duplicate resource keys and schema errors **before** auth, so a
  credentials error means validation already passed.
- Resource keys are globally unique across every resource type in the bundle.
- For targets and deployment modes, variable interpolation, resource types, Lakebase, post-deploy
  runs, and the deploy-time traps, read
  [databricks-asset-bundles](../../databricks-asset-bundles/SKILL.md).
