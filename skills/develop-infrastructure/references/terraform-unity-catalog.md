# Terraform: the Unity Catalog / account console plane

> **Source.** `[repo]` — from a production Terraform configuration (providers `azurerm ~> 3.0`,
> `databricks`, `Azure/azapi`, `hashicorp/time`) and its fix history. `[docs]` marks a
> provider-documented behaviour; `[deduced]` an inference from the code and commit sequence.

## Provider setup: two Databricks providers, one Azure identity

```hcl
terraform {
  backend "azurerm" {}                       # fully configured via -backend-config at init
  required_providers {
    azurerm    = { source = "hashicorp/azurerm", version = "~> 3.0" }
    databricks = { source = "databricks/databricks" }
    azapi      = { source = "Azure/azapi" }
  }
}

provider "azurerm" { features {} }
provider "azapi" {}

provider "databricks" {                      # workspace level (default, unaliased)
  host      = data.azurerm_databricks_workspace.this.workspace_url
  auth_type = "azure-cli"
}

provider "databricks" {                      # account level (aliased)
  alias      = "account"
  host       = "https://accounts.azuredatabricks.net"
  account_id = var.databricksAccountId
  auth_type  = "azure-cli"
}
```

- **Two providers are unavoidable.** Workspace-scoped resources (catalogs, external locations,
  grants, entitlements) go to the workspace host; account-scoped ones (groups, group roles,
  permission assignments, NCC) go to `accounts.azuredatabricks.net` with an `account_id`. There is no
  single endpoint that serves both.
- `host` for the workspace provider comes from the **azurerm data source**, not a variable — the
  workspace URL is only known after creation:
  ```hcl
  data "azurerm_databricks_workspace" "this" {
    name                = var.workspaceName
    resource_group_name = var.workspaceRgName
  }
  ```
- **`auth_type = "azure-cli"` is the answer that worked.** The history shows a long detour:
  `TerraformTaskV4` injects only `ARM_CLIENT_ID`/`ARM_TENANT_ID`, so the Databricks provider was
  hand-fed `ARM_CLIENT_SECRET` via `##vso[task.setvariable]`, then a PAT (`DATABRICKS_TOKEN`) was
  tried with the `ARM_*` variables blanked out. The stable end state is: run Terraform inside
  `AzureCLI@2` with `addSpnToEnvironment: true`, and let both providers use the CLI's session. Don't
  reintroduce `ARM_*` marshalling.
- `azure_workspace_resource_id` on the provider is **not** needed when `host` is set and the CLI is
  authenticated; the repo removed it.
- `backend "azurerm" {}` with an empty body is deliberate — every value arrives as
  `-backend-config=...` at `init`, so one configuration serves every environment (see
  [azure-devops-pipelines.md](./azure-devops-pipelines.md)).
- Child modules that need an aliased provider must declare it:
  ```hcl
  terraform {
    required_providers {
      databricks = {
        source                = "databricks/databricks"
        configuration_aliases = [databricks.account, databricks.workspace]
      }
    }
  }
  ```
  and the caller passes `providers = { databricks.account = databricks.account, databricks.workspace = databricks }`.
  Note the asymmetry: the *unaliased* parent provider is mapped onto the child's
  `databricks.workspace` alias.

## The credential chain (order is the whole game)

```
azurerm_databricks_access_connector        (system-assigned managed identity)
  └─> azurerm_role_assignment              "Storage Blob Data Contributor" @ storage account scope
        └─> databricks_storage_credential  azure_managed_identity { access_connector_id }
              └─> databricks_external_location   abfss://<container>@<account>.dfs.core.windows.net
                    └─> databricks_catalog       storage_root = same abfss:// URL
                          └─> databricks_grant   per (group, catalog)
```

```hcl
resource "azurerm_databricks_access_connector" "db_mi" {
  name                = var.accessConnectorName
  resource_group_name = var.accessConnectorRg
  location            = data.azurerm_resource_group.this.location
  tags                = local.tags
  identity { type = "SystemAssigned" }
}

# ONCE, at storage-account scope — not per catalog
resource "azurerm_role_assignment" "db_mi_data_contributor" {
  scope                = data.azurerm_storage_account.db_uc_catalog.id
  role_definition_name = "Storage Blob Data Contributor"
  principal_id         = azurerm_databricks_access_connector.db_mi.identity[0].principal_id
  depends_on           = [data.azurerm_storage_account.db_uc_catalog]
}

resource "databricks_storage_credential" "db_uc_storage_cred" {
  name = "${var.catalogStorageAccountName}credential"
  azure_managed_identity { access_connector_id = azurerm_databricks_access_connector.db_mi.id }
  comment    = "Managed identity credential managed by TF"
  depends_on = [azurerm_role_assignment.db_mi_data_contributor]
}
```

Why this shape:

- **The access connector is the passwordless path.** No storage keys, no SAS, no secrets in state.
  It is an Azure resource with a managed identity that Databricks is allowed to assume.
- **One role assignment, at account scope.** Granting per container multiplies assignments for no
  benefit and hits the 2000-assignments-per-subscription ceiling fast. `[deduced]`
- `identity[0].principal_id` — the identity block is a list even when there is exactly one.
- **`depends_on` is mandatory here, not stylistic.** Terraform infers dependencies from attribute
  references; `databricks_storage_credential` references the *connector*, not the *role assignment*,
  so without `depends_on` it races ahead and fails with a permission error. Azure RBAC propagation is
  seconds-to-minutes.
- When propagation still loses the race, add a `time_sleep`:
  ```hcl
  resource "time_sleep" "wait" { create_duration = "20s" }
  ```
  The repo's history shows this delay repeatedly tuned (20 s → 60 s) and also moved into the pipeline
  as a plain `sleep 60` after a storage network-rule change, with the note: *"Azure storage network
  rule changes typically propagate in 10–60 seconds, but Microsoft docs note it can take up to 5
  minutes in some cases."* Treat any eventual-consistency wait as a tuning parameter, and prefer
  `depends_on` first — a sleep only hides ordering you did not declare.

## External locations and catalogs

```hcl
resource "databricks_external_location" "db_ext_loc" {
  name = var.external_location_name
  url  = format("abfss://%s@%s.dfs.core.windows.net",
                data.azurerm_storage_container.db_uc_catalog.name, var.storage_account_name)
  credential_name = var.storage_credential_id
  comment         = "Tags:\n\n${join("\n", [for k, v in var.tags : "${k}: ${v}"])}"
  force_destroy   = var.force_destroy_external_location     # default false
}

resource "databricks_catalog" "catalog" {
  name           = var.catalog_name
  storage_root   = format("abfss://%s@%s.dfs.core.windows.net",
                          data.azurerm_storage_container.db_uc_catalog.name, var.storage_account_name)
  isolation_mode = "ISOLATED"                                # not "OPEN"
  force_destroy  = var.force_destroy_catalog                 # default false
  depends_on     = [databricks_external_location.db_ext_loc]
}
```

- **The URL is `abfss://<container>@<account>.dfs.core.windows.net`** — the `dfs` endpoint, not
  `blob`, and no trailing slash. Using `blob.core.windows.net` fails on an HNS account.
- **Names are metastore-global.** Both `external_location` and `catalog` live in a metastore shared
  by every workspace in the region, so a bare `bronze` collides across workspaces. The repo's fix:
  ```hcl
  external_location_name = replace("${var.workspaceName}_${each.value}", "-", "_")
  catalog_name           = replace("${var.workspaceName}_${each.value}", "-", "_")
  ```
  The `external_location_name` originally omitted the workspace prefix and was corrected in a commit
  titled exactly *"Incorporate workspaceName into external_location_name to prevent clash across
  environments"*. Prefix both.
- **`replace(..., "-", "_")` is required**, not cosmetic: Unity Catalog identifiers reject hyphens,
  but Azure container names commonly use them (`bronze-sensitive`, `client-<name>`).
- `isolation_mode = "ISOLATED"` prevents the default "all workspaces in the metastore can see this
  catalog". Set it explicitly on anything with sensitive data; the default is permissive.
- `force_destroy` defaults to `false` on both, with a comment on each variable. `true` deletes the
  catalog **and all schemas/tables/volumes in it**. The history shows it flipped to `true` during
  bring-up and flipped back with a TODO — if you set it `true` for iteration speed, put the revert in
  the same commit's TODO and track it.

### The `.id` vs `.name` trap

```hcl
# resource: .id IS the name
storage_credential_id = databricks_storage_credential.db_uc_storage_cred.id      # ok

# data source: .id is an internal UUID
storage_credential_id = data.databricks_storage_credential.db_uc_storage_cred.name
# NOTE: Using .name, not .id — the data source returns an internal UUID for .id,
# whereas the catalog module passes this to credential_name which expects the name string.
```

`databricks_external_location.credential_name` wants the credential's **name**. The *resource*'s
`.id` happens to be the name, so a root module that creates the credential can pass `.id`; a
standalone module that *looks it up* must pass `.name`. This asymmetry cost a debugging cycle in the
repo and is called out in a code comment — keep that comment.

### `azurerm` 3.x vs 4.x container attribute

```hcl
resource "azurerm_storage_container" "catalog" {
  name                  = var.catalogName
  storage_account_name  = var.catalogStorageAccountName   # azurerm 3.x
  # storage_account_id  = data.azurerm_storage_account...id  # azurerm 4.x only
  container_access_type = "private"
}
```

`storage_account_id` on `azurerm_storage_container` is a 4.x attribute. With `version = "~> 3.0"`
pinned it is an unknown-argument error — the repo has a commit reverting exactly that. Check the
pinned major before using a newer attribute.

## Grants: singular is additive, plural is authoritative

```hcl
# Using databricks_grant (singular) for additive grants per principal
# This allows multiple groups to have grants on the same catalog
resource "databricks_grant" "catalog" {
  catalog    = var.catalog
  principal  = var.principal
  privileges = var.privileges
}
```

- **`databricks_grant` (singular)** manages one principal's privileges on one securable — additive,
  so N groups can be granted independently from N module instances.
- **`databricks_grants` (plural)** is authoritative for the whole securable: applying it replaces
  every grant on that object, silently removing grants made elsewhere. `[docs]`
- With `for_each` over groups, the plural resource would mean the last-applied module wins. Use the
  singular one for per-group modules. This is the single most destructive mistake available in this
  layer.

### Expanding group × container into a stable `for_each` map

```hcl
group_container_pairs = {
  for pair in flatten([
    for group_name, grant_config in local.grants_config : [
      for container in grant_config.containers : {
        key          = "${group_name}-${container}"
        group_name   = group_name
        grant_config = grant_config
        container    = container
      }
    ]
  ]) : pair.key => pair
}
```

```hcl
module "grants" {
  for_each   = local.group_container_pairs
  source     = "./modules/grants"
  catalog    = replace("${var.workspaceName}_${each.value.container}", "-", "_")
  principal  = each.value.group_name
  privileges = each.value.grant_config.privileges
  depends_on = [module.catalogs]
}
```

- The nested comprehension + `flatten` + re-key into a **map** is the idiom. `for_each` over a map
  keys state addresses by the map key, so adding a group does not re-create unrelated grants. A
  `for_each` over a *list* re-indexes everything after an insertion.
- Build the key from the natural compound identity (`"<group>-<container>"`), and never from
  `count.index`.
- `depends_on = [module.catalogs]` at the module level — a grant on a catalog that does not exist yet
  fails, and the privilege list carries no reference to the catalog resource.

### Privilege levels as a named dictionary

```hcl
privilege_levels = {
  ordinary = ["USE_CATALOG","USE_SCHEMA","CREATE_FUNCTION","CREATE_TABLE","EXECUTE","MODIFY","SELECT","READ_VOLUME","WRITE_VOLUME","BROWSE"]
  elevated = ["USE_CATALOG","USE_SCHEMA","CREATE_SCHEMA","CREATE_FUNCTION","CREATE_TABLE","CREATE_VOLUME","EXECUTE","MODIFY","SELECT","READ_VOLUME","WRITE_VOLUME","BROWSE"]
  all      = ["ALL_PRIVILEGES"]
}

groups_with_admins = merge(                      # admins are never omittable
  { "SG-dbx-account-admins" = "all" },
  var.catalogGroups
)
```

- Naming the tiers means the caller passes `{ "<group>" = "elevated" }` instead of a 12-element
  privilege list — an on-demand catalog pipeline can then take a tiny `map(string)` parameter.
- `elevated` − `ordinary` = `CREATE_SCHEMA` + `CREATE_VOLUME`. Keep the diff that small and explicit.
- `merge({admins = "all"}, var.catalogGroups)` with the hardcoded entry **first** means a caller can
  still override the admin group's level, but cannot forget it. If it must be non-overridable, put it
  second.
- `ALL_PRIVILEGES` is a single grant that follows future privilege additions — convenient for admins,
  dangerous for anyone else.

## Entra group sync to the Databricks account

```hcl
locals { groups_config = jsondecode(file("${path.module}/../../../../configuration/groups.global.json")) }

module "groups_account" {
  for_each  = local.groups_config
  source    = "../group/account"
  providers = { databricks.account = databricks.account }

  group_name      = each.key
  entra_object_id = each.value.entra_object_id
}
```

```hcl
# modules/group/account
resource "databricks_group" "account_group" {
  provider     = databricks.account
  display_name = var.group_name
  external_id  = var.entra_object_id      # the Entra (Azure AD) object ID
}
```

- **`external_id` is what links the Databricks group to Entra** and enables membership sync. Key the
  config on the object ID; the history has a commit *"Hardcoded entra object ids instead of group
  names"* — display names are not stable identifiers.
- **Create vs look up.** The repo oscillated: `resource "databricks_group"` → a
  `create_group` boolean switching between `resource` and `data` with
  `try(resource[0].id, data[0].id)` → **`data "databricks_group"` only** → back to `resource` in the
  standalone sync module. The rule that emerges:
  - If an external provisioner (SCIM / Entra enterprise app) creates the groups, use
    **`data "databricks_group"`** and only manage assignments/entitlements. A `resource` fights the
    provisioner.
  - If Terraform is the only writer, use `resource "databricks_group"` with `external_id`.
  - Do **not** build a `create_group` boolean that switches between them — the `try(x[0], y[0])`
    indirection was removed as unnecessary complexity once ownership was decided. Decide ownership.
- Optional keys in the JSON need `try()`:
  ```hcl
  workspace_admin = try(each.value.workspace_admin, false)
  account_admin   = try(each.value.account_admin, false)
  ```
  Without it, every group entry must spell out every flag — the fix commit is *"Removed issue with
  account and workspace admin"*.

### Workspace assignment and entitlements

```hcl
data "databricks_group" "account_group" {
  provider     = databricks.account
  display_name = var.group_name
}

resource "databricks_mws_permission_assignment" "add_user_group" {
  provider     = databricks.account
  workspace_id = var.workspace_id
  principal_id = data.databricks_group.account_group.id
  permissions  = var.workspace_admin == true ? ["ADMIN"] : ["USER"]
}

resource "databricks_entitlements" "workspace_entitlements" {
  provider                   = databricks.workspace
  group_id                   = data.databricks_group.account_group.id
  allow_cluster_create       = true
  allow_instance_pool_create = true
  databricks_sql_access      = true
  workspace_access           = true
  # workspace_consume = true  # cannot be combined with workspace_access or databricks_sql_access
  depends_on = [databricks_mws_permission_assignment.add_user_group]
}

resource "databricks_group_role" "account_admin" {
  count    = var.account_admin ? 1 : 0
  provider = databricks.account
  group_id = data.databricks_group.account_group.id
  role     = "account_admin"
}
```

- Three different scopes in one module: assignment (account provider), entitlements (workspace
  provider), account role (account provider). This is why the module declares both aliases.
- `permissions = ["ADMIN"]` is **workspace** admin; `databricks_group_role` with
  `role = "account_admin"` is **account** admin. They are independent, and the repo's TODO notes the
  privilege distinction between them still needs review — treat `account_admin` as the highest
  privilege in the system and grant it to exactly one group.
- `workspace_consume` conflicts with `workspace_access` / `databricks_sql_access` regardless of its
  boolean value — the commented line records that. Pick the consumer model or the full model.
- `databricks_entitlements` is **authoritative** for the group: omitted entitlements are revoked.
- `depends_on` on the entitlements: the group must be in the workspace before entitlements can be set.

## Serverless connectivity: NCC

```hcl
resource "databricks_mws_network_connectivity_config" "ncc" {
  provider   = databricks.account
  name       = "ncc-for-${var.catalogStorageAccountName}"
  region     = data.azurerm_resource_group.this.location
  depends_on = [module.catalogs]
}

resource "databricks_mws_ncc_private_endpoint_rule" "storage" {
  provider                       = databricks.account
  network_connectivity_config_id = databricks_mws_network_connectivity_config.ncc.network_connectivity_config_id
  resource_id                    = data.azurerm_storage_account.db_uc_catalog.id
  group_id                       = "blob"
  depends_on                     = [module.catalogs]
}
```

- **Serverless compute does not live in your VNet.** VNet injection covers classic compute only;
  serverless SQL warehouses, serverless jobs and Lakeflow pipelines reach storage from Databricks'
  own network. An NCC with a private endpoint rule is how that traffic gets to a firewalled storage
  account. `[docs]`
- `network_connectivity_config_id` is a distinct attribute from `.id` — use the named one.
- `group_id = "blob"` for ADLS; add a `dfs` rule too if the workload uses the filesystem endpoint.
  `[deduced]`
- NCC is **account-level and region-scoped**: one NCC per region, attached to workspaces. The private
  endpoint it creates needs approval on the storage side (automatic when the same tenant owns both).
- The repo's TODO *"In data plane, cut out private endpoint as Databricks workspace seems to be able
  to manipulate storage account via access connector"* captures the design tension: with the access
  connector plus NCC, the hand-built storage private endpoint may be redundant. Decide one path.

## Module layout and standalone modules

```
terraform/
  main.tf  variables.tf  outputs.tf          # root: full console plane (one state)
  modules/
    catalog/            # external location + catalog + container data source
    grants/             # one databricks_grant
    shared/
      catalogs-grants/  # STANDALONE: own backend{}, own providers — one catalog on demand
      groups/account/   # STANDALONE: own backend{}, own providers — Entra group sync
      group/account/    #   leaf: databricks_group
      group/workspace/  #   leaf: assignment + entitlements + account role
    storage/{enable,disable}_public_access/    # STANDALONE, stateless (no backend)
    workspace/{enable,disable}_public_access/  # STANDALONE, stateless (no backend)
```

Three module kinds, deliberately different:

1. **Leaf modules** (`catalog`, `grants`, `group/*`) — no `backend`, no `provider` blocks, only
   `required_providers` (+ `configuration_aliases`). Composable.
2. **Standalone root modules** (`shared/*`) — their own `backend "azurerm" {}` and `provider` blocks,
   so a pipeline can `cd` into them and run them independently with their own state key. This is how
   "create one catalog for a new tenant" became a pipeline that doesn't touch the platform state.
3. **Stateless modules** (`*/enable_public_access`, `*/disable_public_access`) — no backend at all,
   applied with `-auto-approve`. Covered in
   [network-isolation-and-exposure.md](./network-isolation-and-exposure.md).

Notes:

- A standalone module **duplicates the provider and data-source boilerplate**. That duplication is
  the price of independent state; keep the leaf modules shared so the logic isn't duplicated too.
- `jsondecode(file("${path.module}/../../../../configuration/..."))` — the `../` count is coupled to
  the module's depth. Moving a module breaks it silently (there are two such fix commits). When
  relocating, re-count.
- Standalone modules read the *same* config files as the root, so a grant added to
  `grants.internal.json` affects both — intended, but it means the two states can both claim a
  resource. Partition by securable (the on-demand module owns catalogs it created) and never let two
  states manage the same object.

## State, destruction and safety

- State lives in blob storage, keyed per environment / region / increment / module:
  ```
  <env>/<region>/<increment>/terraform.tfstate
  <env>/<region>/<increment>/modules/shared/catalogs-grants/<catalogName>/terraform.tfstate
  ```
  Including the module path *and* the catalog name in the key is what makes per-catalog runs
  independent.
- **`terraform.tfstate*` must be gitignored** — state contains secrets. So must `.terraform/`,
  `tfplan`, and `.terraform.tfstate.lock.info`.
- **Deleting Terraform code destroys infrastructure.** This is in the repo's own TODO list as a
  security concern. Mitigations actually in use: `force_destroy = false` by default, resource-group
  `CanNotDelete` locks (which block an accidental RG delete but *not* a Databricks-API-level catalog
  delete), and plan review in the PR.
- `terraform plan -out=main.tfplan` then `terraform apply main.tfplan` — applying a **saved plan**
  rather than re-planning is what makes the approved change the applied change.
- A local-dev helper (`terraform-flow.sh`: `init -upgrade` → `validate` → `plan` → `apply` → prompted
  `destroy`) is fine for a sandbox. Keep the destroy behind an interactive confirmation that defaults
  to *no*, and never run it in CI.
- `outputs.tf` emitting the computed tag map is a cheap way to verify the config merge without a
  deploy.
