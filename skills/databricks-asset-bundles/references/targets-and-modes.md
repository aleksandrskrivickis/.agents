# Targets, deployment modes & scoping

> **Source.** `[repo]` — distilled from a production Lakeflow bundle and the deploy failures it
> hit. `[docs]` marks documented Databricks CLI/bundle behaviour; `[deduced]` an inference.

## Targets

A **target** is a named deployment environment under `targets:`. Each can set its own `mode`,
`workspace` (host/`root_path`), `permissions`, `variables`, and `resources`. One target is
`default: true`.

```yaml
targets:
    dev:
        default: true
        mode: development
        workspace:
            root_path: /Workspace/Assets/Bundles/Individual/${workspace.current_user.short_name}/${bundle.name}/${bundle.target}
        permissions:
            - user_name: ${workspace.current_user.userName}
              level: CAN_MANAGE
            - group_name: users
              level: CAN_VIEW
        variables:
            schema: ${workspace.current_user.short_name}_dev
        resources:
            pipelines:
                my-pipeline:
                    configuration:
                        limit_per_source: ${var.limit_per_source}   # dev-only override
    prod:
        mode: production
        workspace:
            root_path: /Workspace/Assets/Bundles/${bundle.name}/${bundle.target}
        permissions:
            - group_name: <data-engineers-group>
              level: CAN_MANAGE
        variables:
            schema: my_schema_prod
```

## `mode: development` vs `mode: production`

`mode: development`:
- **Prefixes every resource name** with `[dev <user>]`, and **pauses** job schedules/triggers.
- Deploys an isolated per-user copy — safe to redeploy repeatedly.

`mode: production`:
- No prefix, schedules run as written. Used for shared/prod targets.
- Keep a prod schedule explicitly `pause_status: PAUSED` while a target is being built out.

### A shared target in development mode is a per-user sandbox

> **The trap that reads as a near-production environment.** Setting `mode: development` on a target
> everyone treats as "shared, nearly production" gives it development semantics: resources are
> user-prefixed, schedules are paused by default, and if the schema is derived from
> `${workspace.current_user.short_name}` then **each developer gets their own**. Anyone reading
> results from that target as production-representative is reading their own sandbox.

In the source project a `fiat` target carried `mode: development` with no comment explaining why,
while the team discussed its outputs as pre-production evidence. If a target is shared, make it
`mode: production` and get isolation from `workspace.root_path` and permissions instead. If it must
be development mode, say so in a comment next to the key, and state who the results are valid for.

## Name prefixing — the endpoint trap

The dev prefix `[dev <user>] ` is passed through the CLI's `normalizePrefix`, which for identifiers
that can't contain spaces/brackets (serving endpoints) becomes `dev_<short_name>_`. So a serving
endpoint `my_model` deploys as `dev_<short_name>_my_model`.

- **Serving-endpoint names are workspace-GLOBAL**, so a prefixed dev copy breaks any shared name and
  multiple users collide.
- **Schemas** have a per-resource opt-out (`Experimental.SkipNamePrefixForSchema`); **endpoints do
  not**.
- `presets: {name_prefix: ""}` at target level does **NOT** disable the prefix in development mode —
  the CLI treats the empty string as *unset* and re-applies `[dev <user>] `. (Verified in the CLI's
  `transformDevelopmentMode`.)
- **Therefore**: deploy anything that needs a stable, unprefixed name (serving endpoints) **only from
  a `production`-mode target**, or create it out-of-band and just *reference* it from dev. Don't try
  to unprefix a development target.

## `include` scoping (there is no per-target include)

```yaml
include:
    - resources/*.yml        # TOP-LEVEL / GLOBAL only
```

- `targets.<t>.include` does **not** exist. Every globally-included pipeline/job applies to **all**
  targets and can't be excluded from one. A "model-only" target is impossible while the pipeline/job
  files are globally included (they tag along and demand their variables).
- **Per-target scoping = inline** under `targets.<t>.resources.<type>.<key>`. Define a resource once
  (globally or inline) and *override* fields per target by repeating the same resource key under the
  target.
- `mode:` placed at the top of an included resource file is an **unknown field, ignored**. Prefixing
  is decided solely by the deployed *target's* mode, regardless of where the resource is declared.

## Permissions & workspace

- `permissions:` at the top level apply bundle-wide; per-target `permissions:` add/override for that
  target (e.g. a personal `CAN_MANAGE` in dev, a group in prod).
- `workspace.root_path` controls where assets land; a per-user dev path
  (`.../Individual/${workspace.current_user.short_name}/...`) keeps dev copies isolated.
- `workspace.host` is literal (see variables reference — it can't take `${var.*}`).

## An admin-only target for shared infrastructure

Some resources are not per-environment: a Lakebase project, the branches every environment forks
from, a model-serving endpoint whose name must be stable, a one-off registration job. Deploying them
from `dev` means a developer's redeploy can disturb `prod`; deploying them from `prod` means a
routine production deploy carries cross-environment blast radius.

The pattern is a **fifth target that owns only shared objects**, deployed deliberately and rarely:

```yaml
targets:
    shared:
        mode: production                         # names must be stable
        workspace:
            root_path: /Workspace/Assets/Bundles/${bundle.name}/${bundle.target}
        permissions:
            - group_name: <platform-admins>
              level: CAN_MANAGE
            - group_name: users
              level: CAN_VIEW
        variables:
            schema: ${var.schema_prefix}_${bundle.target}
        resources:
            jobs:
                register-embedding-model:
                    name: ${bundle.name}-${bundle.target}-model-serving
                    tasks:
                        - task_key: register-model
                          notebook_task:
                              notebook_path: ./src/templates/register-embedding-model.py
                              base_parameters: {catalog: ${var.catalog}, model_name: <name>}
            job_runs:                            # fires once per `bundle deploy -t shared`
                embedding-model-registration:
                    job_id: ${resources.jobs.register-embedding-model.id}
            postgres_projects: { ... }           # see lakebase-and-data-api.md
            postgres_branches: { ... }
```

Why it works, and what to watch:

- **`mode: production`** so nothing is `[dev <user>]`-prefixed — the whole point is stable names.
- **Permissions scoped to admins**, which is the enforcement. The target's existence is not a
  guardrail; the ACL is.
- **`job_runs`** makes "deploy = register" one action, so the registration cannot be forgotten.
- **Other targets then *consume* these objects without declaring them.** That is the hazard: a
  serving endpoint is **workspace-global**, so `dev` and `fiat` can read one that only `shared`
  creates, with no declared dependency and nothing checking. In the source project neither of the two
  targets that *used* an endpoint created it. Either add a precondition check to the consuming
  pipeline, or accept the coupling and document it where the consumer reads the name.
- **Deploy `shared` before any target that depends on it**, and note that references crossing targets
  by literal path (Lakebase branches) get no ordering help from the bundle.
- A cross-environment target sits awkwardly in a branch-per-environment model. Either give it its own
  long-lived branch, or accept that it is deployed from one environment's branch and say which.
