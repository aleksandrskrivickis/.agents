# Cluster configuration

> **What this is.** Enabling Databricks Container Services (DCS) so a cluster can run a custom Docker
> image, and injecting a secret into a cluster. From a Databricks example notebook; the workspace URL
> and bearer token are placeholders — read a token from a secret scope, see
> [credential-management](./credential-management.md).

## Enable Databricks Container Services

DCS is a **workspace-level** setting, toggled through `/api/2.0/workspace-conf`. Confirm your auth
against a cluster first, then flip the flag:

```bash
# Confirm auth works
curl --request GET "https://<workspace-url>/api/2.0/clusters/get" \
     --header "Authorization: Bearer <token>" \
     --data '{ "cluster_id": "1234-567890-a12bcde3" }'

# Turn on Databricks Container Services for the whole workspace
curl --request PATCH "https://<workspace-url>/api/2.0/workspace-conf" \
     --header "Authorization: Bearer <token>" \
     --data '{"enableDcs": "true"}'
```

## Inject a secret as a cluster Spark config or environment variable

Do not paste a credential into a cluster config. Store it in a secret scope
([credential-management](./credential-management.md)) and reference it. Databricks resolves the
reference at cluster start and redacts it from notebook output and driver logs. The reference format
is `{{secrets/<scope-name>/<secret-name>}}`.

Spark configuration property (Compute → Advanced → Spark config):

```ini
spark.password {{secrets/my-scope/my-key}}
```

```python
spark.conf.get("spark.password")  # shows [REDACTED] if printed
```

Environment variable (Compute → Advanced → Environment variables):

```ini
SPARKPASSWORD={{secrets/my-scope/my-key}}
```

A cluster-scoped init script reads it as a normal shell variable:

```bash
if [ -n "$SPARKPASSWORD" ]; then
  : # use ${SPARKPASSWORD}
fi
```

## Notes

- `enableDcs` is set once per **workspace**, not per cluster. After it is `true`, a cluster can
  declare a custom Docker image.
- Never put a literal bearer token in a notebook. Use a secret scope or OAuth.
- The cluster **owner** needs `CAN READ` on the secret scope. Restart the cluster after you change
  a secret, so it fetches the new value.
- A secret in an environment variable is readable by every user who can attach to the cluster. Scope
  cluster access accordingly.
- `[?]` Confirm DCS is still offered on your Databricks plan before relying on it.
