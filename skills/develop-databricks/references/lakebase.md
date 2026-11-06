# Lakebase

> **What this is.** Administering a Lakebase (managed Postgres) project through the Databricks SDK's
> raw API client. From a Databricks example notebook; the project name is obfuscated.

## Call the Lakebase API with the SDK (auto-auth)

`WorkspaceClient()` authenticates from the notebook's runtime credentials — no host or token needed.
`api_client.do()` then calls any REST endpoint, including ones the typed SDK does not wrap yet.

```python
# /// script
# [tool.databricks.environment]
# environment_version = "6"
# ///
from databricks.sdk import WorkspaceClient

w = WorkspaceClient()  # auto-auth from the notebook runtime; no host/token literal

# Delete a Lakebase (Postgres) project, purging its data
w.api_client.do(
    "DELETE",
    "/api/2.0/postgres/projects/my-project",
    query={"purge": True},
)
```

## Notes

- The `# /// script … environment_version = "6"` header pins the notebook's serverless environment.
- `api_client.do(method, path, query=..., body=...)` is the escape hatch for any REST endpoint the
  typed SDK does not expose yet.
- `purge=True` is **destructive and irreversible** — it deletes the project's data, not just the
  reference.
- To provision Lakebase projects and synced tables as bundle resources, see
  [databricks-asset-bundles](../../databricks-asset-bundles/SKILL.md).
