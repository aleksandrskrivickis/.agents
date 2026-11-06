# File operations

> **What this is.** Copying files and notebooks around a Databricks workspace. From Databricks
> example notebooks; the user path, library path, host and token are obfuscated.

## Copy files on DBFS or Workspace with shell

```bash
# -rn = recursive, no-clobber (skip files that already exist)
cp -rn "/Workspace/Repos/my-library/data-preparation/"* "/dbfs/mnt/ingestion/data-preparation-dirty"

ls -la /dbfs/mnt/ingestion/
```

## Copy a notebook across paths via the Workspace API

Shell `cp` does not move **notebooks** between Workspace paths cleanly. Use the Workspace
export/import API: export the source as `SOURCE`, base64-encode it, import it to the destination.

```python
import requests, base64

DATABRICKS_HOST = "https://<workspace-url>"
TOKEN = dbutils.secrets.get("workspace", "pat")  # never a literal dapi… token
SOURCE_PATH = "/Workspace/Repos/my-library/data-preparation"
DEST_PATH = "/Workspace/Users/<user>/data-preparation"

headers = {"Authorization": f"Bearer {TOKEN}"}

export = requests.get(
    f"{DATABRICKS_HOST}/api/2.0/workspace/export",
    headers=headers,
    params={"path": SOURCE_PATH, "format": "SOURCE", "direct_download": "true"},
)
export.raise_for_status()

content_b64 = base64.b64encode(export.content).decode("utf-8")
imp = requests.post(
    f"{DATABRICKS_HOST}/api/2.0/workspace/import",
    headers=headers,
    json={"path": DEST_PATH, "format": "SOURCE", "content": content_b64, "overwrite": True},
)
imp.raise_for_status()
```

## Notes

- Read the token from a secret scope ([credential-management](./credential-management.md)); never
  hardcode a `dapi…` PAT.
- `export`/`import` handle one notebook. For a whole tree use the CLI:
  `databricks workspace export-dir <src> <local>` then `import-dir <local> <dest>`.
- `cp -rn` skips files that already exist; drop the `n` to overwrite.
