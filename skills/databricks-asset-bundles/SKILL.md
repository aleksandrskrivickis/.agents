---
name: databricks-asset-bundles
description: 'Use when working with Databricks Asset Bundles (DAB) — the databricks.yml / resources/*.yml config deployed with the Databricks CLI (bundle validate/deploy/run). Covers targets & deployment modes (development vs production, name prefixing), bundle variables and ${var}/${bundle}/${workspace}/${resources.*} interpolation, the resource types (pipelines, jobs, job_runs, model_serving_endpoints, postgres_* / Lakebase synced tables), per-target resource overrides, post-deploy run-once via job_runs, synced-table pipeline bin-packing, the wheel artifact build, and the many deploy-time gotchas. Distilled from the databricks-web-scraping bundle.'
---

# Databricks Asset Bundles (DAB)

> **What this is.** A **bundle** is an infrastructure-as-code project for Databricks: a root
> `databricks.yml` plus `resources/*.yml`, deployed with the Databricks CLI
> (`databricks bundle deploy/run/validate`). It packages pipelines, jobs, model-serving endpoints,
> Lakebase/Postgres resources, permissions and workspace layout, parameterised per **target**
> (dev / staging / prod).
>
> Distilled from a production Lakeflow bundle and its deploy failures. The product was renamed to
> *Declarative Automation Bundles*, but the `databricks.yml` file and the `databricks bundle` CLI are
> unchanged, so "DAB" still reads correctly — see [develop-sdp](../develop-sdp/SKILL.md) for the
> naming timeline.

## Detailed references

- [references/targets-and-modes.md](./references/targets-and-modes.md) — targets, `mode: development` vs `production`, name prefixing & `normalizePrefix`, presets, per-target `workspace`/`permissions`/`resources`, `include` scoping, the per-user-sandbox trap, and an admin-only target for shared infrastructure.
- [references/variables-and-interpolation.md](./references/variables-and-interpolation.md) — `variables:`, required vars, `${var.*}` / `${bundle.*}` / `${workspace.*}` / `${resources.*.status.*}`, what can't be interpolated, map deep-merge vs array replace.
- [references/resources-and-deploy.md](./references/resources-and-deploy.md) — resource types & key uniqueness, pipeline `configuration`/`environment`, `job_runs` post-deploy, synced-table bin-packing, the wheel artifact, and the deploy/validate/run commands.
- [references/lakebase-and-data-api.md](./references/lakebase-and-data-api.md) — `postgres_projects` and `postgres_branches` field by field, enabling the PostgREST-style Data API, the role/`authenticator` grant trap, and where the declarative surface stops and a script takes over.

## Minimal shape

```yaml
bundle:
    name: my-bundle
    uuid: <stable-uuid>

include:
    - resources/*.yml                 # top-level ONLY — there is no per-target include

artifacts:
    python_artifact:
        type: whl
        build: uv build --wheel
        dynamic_version: true

variables:
    catalog: {default: my_catalog}
    schema:  {description: "Required; each target sets its own."}   # no default = required

workspace:
    host: https://<workspace>.azuredatabricks.net    # literal — NOT ${var.*}-interpolatable

targets:
    dev:
        default: true
        mode: development                             # [dev <user>] prefix + paused schedules
        workspace:
            root_path: /Workspace/Assets/Bundles/Individual/${workspace.current_user.short_name}/${bundle.name}/${bundle.target}
        variables:
            schema: ${workspace.current_user.short_name}_dev
    prod:
        mode: production
        variables:
            schema: my_schema_prod
```

## The rules that prevent most deploy failures

1. **Resource keys are GLOBALLY unique** across *all* resource types, not per type.
   `resources.pipelines.foo` + `resources.postgres_projects.foo` → `bundle validate` error
   "Duplicate key foo". Differentiate the keys; the key is bundle-internal and separate from the
   deployed `name`/`id` fields, so rename freely.
2. **`workspace.host` is NOT `${var.*}`-interpolatable.** Host is resolved during auth config
   *before* bundle variables expand, so `${var.host}` leaks literally → `invalid character "{" in
   host name`. Keep host literal (or per-target, or `DATABRICKS_HOST`/profile).
3. **`mode: development` renames resources.** The CLI prefixes every resource with `[dev <user>]`
   and pauses schedules. For names that must stay stable (serverless endpoints are **workspace-global**),
   deploy them from a `production`-mode target — `presets.name_prefix: ""` does **not** work in dev
   mode (Go treats empty string as unset and re-applies the prefix).
4. **`include:` is top-level only.** No `targets.<t>.include`. A globally-included pipeline/job can't
   be excluded from a target — per-target scoping is done by nesting under `targets.<t>.resources`.
   `mode:` written inside an included resource file is ignored (mode is a *target* property).
5. **Pipeline `configuration` (a map) deep-merges** across target overrides; **task lists (arrays)
   replace**. So a per-target job override must restate the FULL `tasks:` list, but a per-target
   `configuration:` need only add/override keys.
6. **`${bundle.target}` substitutes verbatim** — no case/hyphen transforms. Target `fiat-individual`
   → schema `..._fiat-individual` (an awkward UC identifier); hardcode the schema for such targets.
7. **Never deploy to a shared/prod target without explicit instruction**, and keep bundle *tests*
   read-only (`bundle validate`) — never auto-deploy, even behind a flag.
8. **A default that production does not override reaches production.** A variable defaulted to a
   convenient development value — a personal schema, a sample size, a test table — is live in every
   target that stays silent about it. In the source project a production data-quality stage read one
   named individual's personal development schema, because `prod` never overrode the default and
   nothing made the dependency visible from `prod`'s own configuration. Either give risky variables
   **no default** (so a target must state one) or override them explicitly in every target.
9. **Configuration set only in `dev` leaves every other target on an unrecorded platform default.**
   Retry counts, flow retries, idle shutdown, row caps: if they appear under one target, nobody can
   state what the others do. Set them everywhere, even to the same value as the default.
10. **A schedule is a latency decision.** `pause_status`, the cron, and `max_retries: 0` together
    determine how long a change can go undetected — a weekly cron with no retries means one transient
    failure costs a full week. Write the acceptable latency down somewhere the cron can be checked
    against. Note that `max_concurrent_runs: 2` is needed if a task in the job pauses the job's own
    schedule.
11. **Some Lakebase objects cannot be declared at all.** The Data API and its Postgres roles are
    imperative: a role created via the `postgres_roles` resource **cannot be granted to
    `authenticator`**, so it must be created in-database by a script. Put that script behind a
    `job_runs` post-deploy hook rather than running it by hand.

## Quick symptom → fix index

| Symptom | Likely cause / fix | Reference |
|---|---|---|
| `Duplicate key <k>` at validate | two resources (any types) share a key — rename one | resources-and-deploy |
| `invalid character "{" in host name` | `${var.*}` in `workspace.host` — use a literal | variables-and-interpolation |
| Endpoint deployed as `dev_<user>_<name>` | dev-mode prefix; deploy endpoint from a prod target | targets-and-modes |
| Per-target job lost its tasks | array replace — restate the full `tasks:` list | variables-and-interpolation |
| `CATALOG_DOES_NOT_EXIST` on synced table | `synced_table_id` is a literal 3-part name; point `catalog` at a real catalog | resources-and-deploy |
| `field data_synchronization_status not found` | use `...status.pipeline_id` for autoscaling synced tables | resources-and-deploy |
| Post-deploy run needed | `job_runs` resource (CLI ≥ 1.7.0 + direct engine); `scripts` are manual only | resources-and-deploy |
| "required variable" never raised | a no-default var is enforced only when the selected target references it | variables-and-interpolation |
| Production reads a developer's schema | a variable default no target overrode | targets-and-modes |
| A "shared, near-production" target behaves per-user | it carries `mode: development` | targets-and-modes |
| Endpoint exists in one environment, missing in another | it is workspace-global and only one target declares it | targets-and-modes |
| Synced table deployed before its Lakebase branch | branches are referenced by literal path — no bundle ordering | lakebase-and-data-api |
| Data API returns 403 for a granted principal | role not granted `TO authenticator`, or created via `postgres_roles` | lakebase-and-data-api |
| Data API 403 only on newly added tables | `GRANT … ON ALL TABLES` is a snapshot; re-run or set default privileges | lakebase-and-data-api |
| New schema invisible over the Data API | it is not in the Data API's `db_schemas` list | lakebase-and-data-api |

## Commands

```bash
databricks bundle validate -t <target>     # structural check (local); dup-key/schema errors surface before auth
databricks bundle deploy   -t <target>     # dev is the default target
databricks bundle run <job-or-pipeline-key> -t <target>
```

- `bundle validate -o json` shows the **pre-substitution** config — `${var.*}` appear **unexpanded**;
  that is NOT proof a resource ignores a variable. Interpolation happens at deploy; read resolved
  values in the deploy request / the UC error, not `-o json`.
- Reaching an **auth** error on `validate` means structural validation already passed (dup-key /
  schema / required-var checks run locally, before auth).

## When to use this skill

- Editing `databricks.yml` or `resources/*.yml`; adding a target, variable, or resource.
- Choosing dev vs prod mode, debugging name prefixing, or per-target resource overrides.
- Wiring post-deploy automation (`job_runs`), Lakebase projects/branches/synced tables, the Data
  API, or the wheel artifact.
- Auditing deployment defaults — schedules, retries, row caps — for values that only exist in one
  target.

## Related skills

- [develop-sdp](../develop-sdp/SKILL.md) — the **pipeline body** this bundle deploys: the `dp` API,
  expectations, the event log, refresh semantics. This skill is the deploy layer around it.
- [develop-pyspark](../develop-pyspark/SKILL.md) — and
  [model registration](../develop-pyspark/references/model-registration-and-endpoints.md) for the
  serving endpoints a bundle declares.
- [develop-infrastructure](../develop-infrastructure/SKILL.md) — the Azure platform the workspace,
  storage and Unity Catalog live on, underneath the bundle.
- [test-python](../test-python/SKILL.md) — bundle validation and wheel-build tests.
- [document-decisions](../document-decisions/SKILL.md) — for the schedules, retry counts and
  per-target limits rules 8–10 keep telling you to write a reason for.
