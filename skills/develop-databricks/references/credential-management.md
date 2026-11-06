# Credential management (secret scopes)

> **What this is.** Storing credentials in Databricks secret scopes and reading them at run time,
> instead of writing an API key or password into a notebook. Written from the Databricks "Secret
> management" docs. To inject a secret into a cluster config, see
> [cluster-configuration](./cluster-configuration.md).

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

## Notes

- Prefer Unity Catalog storage credentials and external locations for cloud storage access, over a
  storage key held as a secret.
- A Key Vault-backed scope is read-only from Databricks; rotate those secrets in Key Vault.
- Reference a secret in a cluster Spark config or environment variable with
  `{{secrets/<scope>/<key>}}` — see [cluster-configuration](./cluster-configuration.md).

## Upstream documentation (source)

- Secret management: https://docs.databricks.com/en/security/secrets/index.html
- Use a secret in a Spark config or environment variable:
  https://docs.databricks.com/en/security/secrets/secrets-spark-conf-env-var.html
