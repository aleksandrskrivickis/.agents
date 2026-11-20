# Lakebase: projects, branches, and serving a synced table over HTTP

> **Source.** `[repo]` — from a production bundle that declares a Lakebase project and branches,
> syncs Unity Catalog tables into them, and exposes one schema as a read-only HTTP API consumed
> through an API gateway, plus a Databricks example notebook for the raw-API-client section.
> `[docs]` marks documented Databricks behaviour; `[deduced]` an inference.

[dab-resources-and-deploy.md](./dab-resources-and-deploy.md) covers the `postgres_synced_tables` resource and
its bin-packing. This file covers what sits **under** it (the project and branch the tables live in)
and what sits **over** it (the Data API that serves them), because that is where the
bundle-declarable surface stops and a hand-run script takes over.

## The layering

```
postgres_projects          the Lakebase instance          ← declared in the bundle
  └─ postgres_branches     a database branch per env      ← declared in the bundle
       └─ database         auto-created, named per branch
            ├─ synced tables   replicas of UC tables      ← declared in the bundle
            └─ Data API        PostgREST-style HTTP face  ← NOT bundle-declarable; a script
                 └─ roles + grants                        ← NOT bundle-declarable; a script
```

> **The split is the thing to plan around.** Everything above the Data API is declarative and
> deploys with `bundle deploy`. The Data API and its grants are **imperative**, so they belong in a
> notebook or script that a `job_runs` post-deploy hook invokes — otherwise they drift the moment
> anyone adds a schema.

## Declaring the project and its branches

```yaml
targets:
    shared:                                   # admin-only target — see dab-targets-and-modes.md
        mode: production
        resources:
            postgres_projects:
                my-lakebase:
                    project_id: ${bundle.name}
                    display_name: ${bundle.name}
                    pg_version: 16
                    default_endpoint_settings:
                        autoscaling_limit_min_cu: 0.5
                        autoscaling_limit_max_cu: 2
                        suspend_timeout_duration: 3600s
            postgres_branches:
                dev:
                    parent: ${resources.postgres_projects.my-lakebase.id}
                    branch_id: dev
                    no_expiry: true
                fiat:
                    parent: ${resources.postgres_projects.my-lakebase.id}
                    branch_id: fiat
                    no_expiry: true
```

| Field | Notes |
|---|---|
| `project_id` | The stable identity. `${bundle.name}` keeps it aligned with everything else. |
| `pg_version` | Pin it. A major-version change is not an in-place edit. |
| `autoscaling_limit_min_cu` / `_max_cu` | Compute units. `0.5` min is the floor; set the max from the read concurrency you expect, not from the data size. |
| `suspend_timeout_duration` | Idle time before the endpoint suspends. `3600s` keeps it warm for an hour — a recurring cost. Shorten it for environments nobody queries between runs. `[deduced]` |
| `parent` | **Does** take a resource reference (`${resources.postgres_projects.<key>.id}`), so the bundle enforces project-before-branch ordering. |
| `no_expiry: true` | Without it a branch can be reaped. Set it on anything an environment depends on. |

Two structural points:

- **Branches fork from the auto-created `production` default branch.** A new `dev` branch starts as a
  copy-on-write fork of it, which is why standing up a new environment is cheap.
- **A synced table references its branch by a *literal path***
  (`projects/<name>/branches/<b>`), not a resource reference — so the bundle will **not** order a
  synced table after the branch it writes into. Deploy the target that owns the project and branches
  *before* the target that syncs into them. This is the one ordering the bundle cannot enforce for
  you.

## The Data API: PostgREST over a synced schema

Enabling it is an SDK call, not a bundle resource:

```python
from databricks.sdk import WorkspaceClient
from databricks.sdk.errors import NotFound
from databricks.sdk.service.postgres import DataApi, DataApiDataApiSpec, OpenApiMode

w = WorkspaceClient()
branch_name = f"projects/{project}/branches/{branch}"

database_resource = next(
    d for d in w.postgres.list_databases(parent=branch_name)
    if d.status and d.status.postgres_database == database
)
data_api_name = f"{database_resource.name}/data-api"

try:
    data_api = w.postgres.get_data_api(name=data_api_name)
except NotFound:
    w.postgres.create_data_api(
        parent=database_resource.name,
        data_api=DataApi(spec=DataApiDataApiSpec(
            db_schemas=["public", schema],         # only these are exposed
            db_max_rows=1000,                      # server-side page ceiling
            openapi_mode=OpenApiMode.OPEN_API_MODE_IGNORE_PRIVILEGES,
            server_timing_enabled=True,
        )),
    ).wait()
    data_api = w.postgres.get_data_api(name=data_api_name)

print(data_api.status.url)
```

- **`try get / except NotFound / create` is the idempotence pattern** — there is no upsert. Run the
  script on every deploy and it is a no-op after the first.
- **`db_schemas` is the exposure boundary.** Adding a schema to the database does not expose it;
  this list does. That is a feature, and it is also why this must be scripted rather than done once
  by hand.
- **`db_max_rows`** caps what a single request can return regardless of what the caller asks for.
- **`openapi_mode`**: `IGNORE_PRIVILEGES` generates an OpenAPI document describing everything in the
  exposed schemas, whether or not the *calling* principal can read it. That makes the spec stable and
  publishable; it also means the spec is not an access-control statement. Choose deliberately.
- `.wait()` on the create — provisioning is asynchronous.

### What the API gives callers

A PostgREST-style query surface over each table:

```
GET {baseUrl}/documents?select=id,content,updated_at   # choose columns
GET {baseUrl}/documents?id=eq.123                      # filter: eq neq gt gte lt lte like in
GET {baseUrl}/documents?order=updated_at.desc          # sort
GET {baseUrl}/documents?limit=50&offset=100            # page
```

Two things to tell consumers explicitly, because the shape invites the wrong assumption:

- **It is read-only.** The table is a synced replica of a Unity Catalog source; writes must go to the
  source, not here. Nothing about the URL says so.
- **Date and timestamp columns are only filterable if they are typed.** A synced column that landed
  as `STRING` cannot be range-filtered usefully, and this was a real finding in the source project:
  the dates the endpoints were *required* to filter on were untyped strings. Check the synced types
  before publishing a filterable API over them.

## Granting a service principal access — and the trap

The grants are plain SQL over a Postgres connection, authenticated with a short-lived Databricks
credential:

```python
import psycopg
from psycopg import sql

endpoint_name = f"projects/{project}/branches/{branch}/endpoints/{endpoint}"
credential = w.postgres.generate_database_credential(endpoint=endpoint_name)
host = w.postgres.get_endpoint(name=endpoint_name).status.hosts.host

connection = psycopg.connect(
    host=host, port=5432, dbname=database,
    user=w.current_user.me().user_name,
    password=credential.token,            # the OIDC token IS the password
    sslmode="require", autocommit=True,
)
```

```python
role = sql.Identifier(service_principal_id)
schema_identifier = sql.Identifier(schema)

with connection.cursor() as cursor:
    cursor.execute("CREATE EXTENSION IF NOT EXISTS databricks_auth;")

    # The in-database path; see "Why the grant to authenticator fails" below.
    with contextlib.suppress(psycopg.errors.DuplicateObject):
        cursor.execute("SELECT databricks_create_role(%s, 'SERVICE_PRINCIPAL');",
                       (service_principal_id,))

    cursor.execute(sql.SQL("GRANT {role} TO authenticator;").format(role=role))
    cursor.execute(sql.SQL("GRANT USAGE ON SCHEMA {s} TO {r};")
                   .format(s=schema_identifier, r=role))
    cursor.execute(sql.SQL("GRANT SELECT ON ALL TABLES IN SCHEMA {s} TO {r};")
                   .format(s=schema_identifier, r=role))
    cursor.execute(sql.SQL("GRANT USAGE ON ALL SEQUENCES IN SCHEMA {s} TO {r};")
                   .format(s=schema_identifier, r=role))
    cursor.execute(sql.SQL("GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA {s} TO {r};")
                   .format(s=schema_identifier, r=role))
```

### Why the grant to `authenticator` fails — and it is not the resource type

This is worth getting exactly right, because the obvious diagnosis is wrong and the correct fix is
*more* declarative, not less.

**The mechanism.** The Data API is PostgREST-compatible: every request connects as the single
Postgres role `authenticator`, which holds `LOGIN` and no privileges, and then runs
`SET ROLE "<service-principal-uuid>"` to assume the caller's identity. Postgres permits that only if
`authenticator` has been **granted** the role. Without the grant:

```
42501  permission denied to set role "d84db70a-f866-4b10-820c-adffd0cd6800"
```

**The actual blocker.** Running the obvious remedy then fails too:

```
permission denied to grant role "d84db70a-f866-4b10-820c-adffd0cd6800"
```

because the service-principal role carries **`DATABRICKS_SUPERUSER` membership**, and Postgres will
not grant an elevated role to `authenticator` — the ability to assume a role cannot be granted for
accounts with elevated privileges. The role's *provenance* is not what blocks it; its *privilege
level* is. `[repo]`

**The fix, in the bundle.** Omitting `membership_roles:` from the `postgres_roles` resource is
documented to strip `DATABRICKS_SUPERUSER` when the role is adopted — so delete the block rather
than editing the role in the UI, or the next `bundle deploy` puts the membership straight back:

```yaml
postgres_roles:
    api-reader:
        role_id: apim-sharedapim-sit-001
        postgres_role: d84db70a-f866-4b10-820c-adffd0cd6800
        replace_existing: true        # adopt a role that was created in the UI
        # membership_roles:  <- REMOVED. Its absence is what strips DATABRICKS_SUPERUSER.
```

Then redeploy, confirm the membership is gone, and run the grants. Look up the real role id with
`databricks postgres list-roles projects/<project-id>/branches/<branch>`.

**Verify in the database, not in the UI**, because the UI's role list shows the declared intent
rather than the resulting Postgres state:

```sql
SELECT r.rolname AS granted_role
FROM pg_auth_members m
JOIN pg_roles r ON r.oid = m.roleid
JOIN pg_roles u ON u.oid = m.member
WHERE u.rolname = 'authenticator';
```

> **An earlier reading of this failure** — recorded in the source project and repeated in community
> threads — concluded that a role created through the management API (the `postgres_roles` resource)
> can *never* be granted to `authenticator`, and that `databricks_create_role(...)` inside the
> database is the only path. The superuser-membership explanation above accounts for the same error
> codes and has a declarative fix, so prefer it. The in-database path still works and remains the
> safe fallback if stripping the membership does not clear the grant — but try the bundle change
> first, because it is the difference between a declared role and a hand-run script. `[?]`

**Check `authenticator` itself while you are there.** By design it should hold `LOGIN` and nothing
else. If it has been declared with `DATABRICKS_SUPERUSER`, strip that too — and not only for
tidiness: `databricks_superuser` carries **`BYPASSRLS`**, so any row-level security you add later is
**silently ignored for every request that arrives over the Data API**. A security control that is
present, configured and inert is worse than one you know you do not have. `[repo]`

Other details that matter:

- **`GRANT <role> TO authenticator` is what makes the Data API able to assume the role.** Without it
  the grants exist and every request still fails — the role is correct and unreachable.
- **`CREATE EXTENSION IF NOT EXISTS databricks_auth`** must come first; `databricks_create_role` is
  provided by it.
- **`psycopg.sql.Identifier`, not f-strings.** A service principal id is a UUID containing hyphens;
  unquoted it is a syntax error, and interpolating identifiers by hand is how SQL injection gets
  into an admin script.
- **`GRANT … ON ALL TABLES IN SCHEMA` is a snapshot**, not a policy — tables created later are not
  covered. Re-run the script after adding a synced table, or add
  `ALTER DEFAULT PRIVILEGES IN SCHEMA <s> GRANT SELECT ON TABLES TO <role>;` so future tables are
  covered too. `[deduced]`
- **The credential is short-lived.** Generate it inside the script run; never cache or log it.
- `contextlib.suppress(psycopg.errors.DuplicateObject)` around the role creation is what makes the
  whole script re-runnable.

## Wiring it into the deploy

```yaml
targets:
    fiat:
        resources:
            jobs:
                bootstrap:
                    tasks:
                        - task_key: run_pipeline
                          pipeline_task: {pipeline_id: ${resources.pipelines.main.id}}
                        - task_key: run_sync          # refresh the synced tables
                          depends_on: [{task_key: run_pipeline}]
                          pipeline_task:
                              pipeline_id: ${resources.postgres_synced_tables.anchor.status.pipeline_id}
                        - task_key: grant_data_api    # idempotent; enables + grants
                          depends_on: [{task_key: run_sync}]
                          notebook_task:
                              notebook_path: ./src/templates/grant-lakebase-data-api-access.py
                              base_parameters:
                                  project_name: ${bundle.name}
                                  branch: ${bundle.target}
                                  database: ${var.catalog}
                                  schema: ${var.schema}
                                  service_principal_id: ${var.api_service_principal_id}
            job_runs:
                post-deploy:
                    job_id: ${resources.jobs.bootstrap.id}
```

- **Order is pipeline → sync → grant.** A grant against a table the sync has not created yet
  succeeds vacuously (`ON ALL TABLES` matches nothing) and leaves the API returning 403s.
- `job_runs` fires it once per `bundle deploy` — see
  [dab-resources-and-deploy.md](./dab-resources-and-deploy.md) for the CLI version it requires.
- Pass the service principal id as a **bundle variable**, not a literal in the notebook. The source
  project had it as a widget default, which is how a principal id for one environment ends up
  granted in another.

## Administering a project with the SDK raw API client

Some project-level operations have no bundle resource and no typed SDK method. `WorkspaceClient()`
authenticates from the notebook's runtime credentials — no host or token literal — and
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

- The `# /// script … environment_version = "6"` header pins the notebook's serverless environment.
- `api_client.do(method, path, query=..., body=...)` is the escape hatch for any REST endpoint the
  typed SDK does not expose yet.
- `purge=True` is **destructive and irreversible** — it deletes the project's data, not just the
  reference. A project a bundle target declares is recreated empty on the next deploy, which reads
  as a successful deploy over lost data.

## Fronting it with an API gateway

If an API-management layer sits in front, the gateway holds the consumer-facing contract:

- A **subscription key** header (e.g. `Ocp-Apim-Subscription-Key`) for the gateway, *plus* a
  **Microsoft Entra bearer token** for the Data API itself. Two credentials, two failure modes — say
  which one a 401 came from in your error docs.
- The gateway's base URL replaces `data_api.status.url`, so consumers never see the Lakebase host.
- **Keep the OpenAPI spec exported from the Data API under version control** and diff it on each
  deploy. The `openapi_mode` above makes the spec stable enough to use as a contract test, and a
  surprise diff is how you notice a schema change reached the public surface.

## Checklist

1. Project and branches declared in an **admin-only target**, with `no_expiry` on anything an
   environment depends on.
2. That target deployed **before** any target with synced tables (literal branch paths, no bundle
   ordering).
3. Data API enablement scripted with `try get / except NotFound / create`, and `db_schemas` listing
   every schema you intend to expose.
4. The API role carries **no `DATABRICKS_SUPERUSER` membership** (no `membership_roles:` block) and
   is granted `TO authenticator`; verified with `pg_auth_members`, not the UI.
5. `authenticator` itself holds `LOGIN` only — no superuser, so `BYPASSRLS` does not void row-level
   security for API traffic.
6. Grants re-run after adding tables, or default privileges set.
7. Service principal id passed as a bundle variable.
8. Grant task ordered after the sync task.
9. Synced column types checked for anything the API must filter on.
10. Exported OpenAPI spec in version control.

## Related

- [dab-resources-and-deploy.md](./dab-resources-and-deploy.md) — `postgres_synced_tables`, bin-packing,
  `job_runs`.
- [dab-targets-and-modes.md](./dab-targets-and-modes.md) — why shared infrastructure wants its own
  admin-only target.
