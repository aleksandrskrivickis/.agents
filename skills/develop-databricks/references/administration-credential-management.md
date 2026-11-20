# Credential management (secret scopes)

> **What this is.** Storing credentials in Databricks secret scopes and reading them at run time,
> instead of writing an API key or password into a notebook. Written from the Databricks "Secret
> management" docs. To inject a secret into a cluster config, see
> [administration-cluster-configuration](./administration-cluster-configuration.md).

## Two kinds of scope

A **secret scope** is a named collection of secrets. There are two backends:

- **Databricks-backed** — Databricks stores the secrets in an encrypted store. You create the scope
  and write secrets with the CLI, the SDK or the Secrets API.
- **Azure Key Vault-backed** — the scope is a view over a Key Vault. You manage the secret **values
  in Key Vault**; from Databricks the scope is read-only.

## Create a scope and add secrets (Databricks-backed)

```bash
databricks secrets create-scope my-scope

databricks secrets put-secret --json '{
  "scope": "my-scope",
  "key": "api-key",
  "string_value": "<secret>"
}'

databricks secrets list-scopes
databricks secrets list-secrets my-scope
```

The scope creator gets `MANAGE` by default. Scope names are case-insensitive and non-sensitive
(any user can list them); secret **values** are not readable through the list APIs.

## Read a secret in a notebook

```python
token = dbutils.secrets.get(scope="my-scope", key="api-key")
dbutils.secrets.list("my-scope")  # metadata (key names) only, not values
```

## Grant access with ACLs

```bash
databricks secrets put-acl my-scope <principal> READ      # READ | WRITE | MANAGE
databricks secrets list-acls my-scope
databricks secrets delete-acl my-scope <principal>
```

The `principal` is a user email, a service principal `applicationId`, or a group name. `READ` lets a
principal read secret values and list the scope; `WRITE` adds writing secrets; `MANAGE` adds managing
ACLs.

## Redaction

Databricks replaces a secret read through `dbutils.secrets.get()` or referenced in a Spark config
with `[REDACTED]` when it is displayed. Redaction applies only to the **literal** value — it cannot
catch a value you deliberately transform (for example, print it one character at a time). Control
access with ACLs; do not rely on redaction alone.

## Secrets on a serverless pipeline: why `{{secrets/...}}` fails silently

The `{{secrets/<scope>/<key>}}` reference form resolves in a **cluster `spark_conf`** — which means
**classic compute only**. On a serverless pipeline there is nothing to hang it on:

- A serverless pipeline **cannot carry a `clusters` block at all**; attempting to add compute
  settings to one is an error. So the documented surface for the reference form does not exist.
- Serverless does not support setting most Spark properties generically either, so you cannot push
  the credential into an arbitrary Spark/Hadoop key instead. `[docs]`
- And in the pipeline-level `configuration:` block, the failure mode is the dangerous one:
  `spark.conf.get()` hands back the **literal string** `{{secrets/scope/key}}`, with no error. A
  connection string silently containing braces is how a credential ends up in a log or a request
  that was never authenticated. `[?]`

The dependable pattern is to split secret from non-secret and resolve the secret in code:

```python
# pipeline `configuration:` holds NON-secret application variables only
#   ingest.scope: my-scope
#   ingest.key:   api-token
scope = spark.conf.get("ingest.scope")
key   = spark.conf.get("ingest.key")
token = dbutils.secrets.get(scope=scope, key=key)   # resolved at run time, on the driver
```

Read it at **module scope** and close over it — `dbutils` is driver-only, so a UDF that calls it
fails on the executor. That is the same rule as
[sdp-python-api.md](./sdp-python-api.md) → *Coding requirements*.

Four operational notes:

- **Bundle YAML can only *define* a scope and its ACLs.** There is no way to read a secret value in
  the bundle; the bundle's job ends at declaring the scope. `[docs]`
- **The run-as identity needs `READ` on the scope.** This is the single most common reason a
  pipeline works in dev and fails in prod — prod runs as a service principal with different ACLs.
  Grant it when you declare the scope, not when it breaks.
- **Rotation applies only to new runs.** A running update will not pick up a rotated value
  mid-flight, so trigger a fresh run after rotating. `[docs]`
- **If a connector genuinely needs the credential as a Spark/Hadoop property** (an ABFS account key,
  say) and you are on serverless, the answer is a **Unity Catalog storage credential or external
  location**, not a conf reference — the conf path is unavailable to you anyway.

## Notes

- Prefer Unity Catalog storage credentials and external locations for cloud storage access, over a
  storage key held as a secret.
- A Key Vault-backed scope is read-only from Databricks; rotate those secrets in Key Vault.
- Reference a secret in a cluster Spark config or environment variable with
  `{{secrets/<scope>/<key>}}` — see [administration-cluster-configuration](./administration-cluster-configuration.md).
  This is **classic compute only**; on serverless see the section above.

## Upstream documentation (source)

- Secret management: https://docs.databricks.com/en/security/secrets/index.html
- Use a secret in a Spark config or environment variable:
  https://docs.databricks.com/en/security/secrets/secrets-spark-conf-env-var.html
