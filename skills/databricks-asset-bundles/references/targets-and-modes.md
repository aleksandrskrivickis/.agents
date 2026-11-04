# Targets, deployment modes & scoping

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
