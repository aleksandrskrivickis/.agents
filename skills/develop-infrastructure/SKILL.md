---
name: develop-infrastructure
description: 'Use when writing or debugging Azure infrastructure-as-code for a Databricks data platform — Bicep deployed at subscription scope, Terraform for the Unity Catalog / account console layer, and Azure DevOps YAML pipelines that orchestrate both. Covers the four-plane split (network / control / data / console), VNet injection with secure cluster connectivity (no public IP), subnet delegation and the required Databricks NSG rules, private endpoints and private DNS zones, NAT gateway egress, ADLS Gen2 with a Data Protection backup vault, access connector + storage credential + external location + catalog + grants, Entra group sync to the Databricks account, serverless NCC private endpoint rules, resource-group CanNotDelete locks, the temporarily-open-firewall deploy pattern, stateless azapi toggle modules, OIDC Terraform backends, az deployment sub validate/what-if preflights, PSRule static analysis, and the naming/tagging conventions. Distilled from a production Azure Databricks platform IaC repo.'
---

# Azure Databricks platform infrastructure-as-code

Problem→solution knowledge from a production Azure Databricks platform built as **four layered
"planes"**: three Bicep deployments (network, control, data) and one Terraform deployment (console —
Unity Catalog and the account console), each driven by its own Azure DevOps pipeline. The hard part
is almost never the resource definitions — it is **ordering, identity, and the fact that the
platform is network-isolated from the agent that deploys it**.

Detailed references:

- [references/plane-architecture-and-naming.md](./references/plane-architecture-and-naming.md) — the four planes and their dependency direction, subscription-scope Bicep, naming-convention constructs and length truncation, the `tagsConfig ∪ tagsRuntime` tag model, config-as-JSON (`parameters`/`grants`/`groups`), the shared-parameter-file trick, mock infrastructure for isolated testing, and VNet address-space planning.
- [references/bicep-azure-resources.md](./references/bicep-azure-resources.md) — VNet/subnets/delegation, the six required Databricks NSG rules, NAT gateway + public IP, the workspace resource, private endpoint + private DNS zone + zone group, ADLS Gen2 storage, the Data Protection backup vault (the ADLS trap), Log Analytics + diagnostics + saved searches, Key Vault, and `bicepconfig.json`.
- [references/terraform-unity-catalog.md](./references/terraform-unity-catalog.md) — dual workspace/account providers, access connector → role assignment → storage credential → external location → catalog, grant expansion and privilege levels, Entra group sync, serverless NCC, `force_destroy` safety, and the `.id`-vs-`.name` traps.
- [references/azure-devops-pipelines.md](./references/azure-devops-pipelines.md) — the dynamically-resolved variable group, branch↔environment guard, lint/validate/what-if preflight, `az deployment sub`, approval gates, lock delete/create, Terraform under `AzureCLI@2` with `addSpnToEnvironment`, OIDC backends, state-key layout, PSRule jobs, and compile-time vs runtime expressions.
- [references/network-isolation-and-exposure.md](./references/network-isolation-and-exposure.md) — the locked-down steady state, why a hosted agent cannot reach it, the open→deploy→close pattern and its stage graph, stateless `azapi` toggle modules, exposure minimisation, and the alternatives.

## The shape

```
1. Network plane   (Bicep, subscription scope) -- VNet, 4 subnets, NSG, NAT GW, public IP
2. Control plane   (Bicep, subscription scope) -- Databricks workspace (VNet-injected, SCC),
                                                  private endpoint, diagnostic settings
3. Data plane      (Bicep, subscription scope) -- ADLS Gen2 + containers, backup vault
4. Console plane   (Terraform, remote state)   -- access connector, storage credential,
                                                  external locations, catalogs, grants,
                                                  Entra groups, NCC
```

One pipeline per plane, run in order. Each Bicep plane is **independently runnable** and re-reads
prior resources with `existing =` rather than consuming outputs from the previous plane — so any
plane can be redeployed alone. Only the Terraform plane holds state.

## The rules that prevent most deploy failures

1. **The platform is closed; the agent is outside it.** Workspace and storage have
   `publicNetworkAccess: Disabled`, and resource groups carry `CanNotDelete` locks. A hosted DevOps
   agent therefore cannot call the Databricks REST API or the blob endpoint. Every Terraform stage
   must **delete locks → open the firewalls → run → close them → recreate locks**, with
   `condition: always()` on every closing stage. Getting the order wrong (opening access *before*
   deleting the locks) fails — the lock blocks the property write.
2. **One parameter file serves every template, so every template must accept every parameter.**
   Declare parameters a template does not use (e.g. `catalogStorageAccountContainers` in the network
   plane) with a default and a comment, or `az deployment sub validate` rejects the shared parameter
   file.
3. **Give every `param` a default.** Templates are validated in CI with only a subset of values
   supplied; a required `param` without a default turns a CI lint into a hard failure. Write
   `param tagsConfig object = {}`, not `param tagsConfig object`.
4. **`union(tagsConfig, tagsRuntime)` — runtime wins.** Config-file tags are the base; pipeline-
   injected tags (environment, change number) override. Never tag from two places without a union.
5. **Unity Catalog names are metastore-global, not workspace-scoped.** An `external_location` or
   `catalog` named `bronze` collides the moment a second workspace shares the metastore. Always
   prefix with the workspace name: `replace("${var.workspaceName}_${container}", "-", "_")` — and
   `replace` the hyphens, because UC identifiers reject them.
6. **Build the credential chain in order, and say so.** Access connector → `azurerm_role_assignment`
   (Storage Blob Data Contributor, at storage-account scope, **once** — not per catalog) →
   `databricks_storage_credential` → `databricks_external_location` → `databricks_catalog`. Azure
   role assignments and storage network-rule changes are eventually consistent (10–60 s, up to
   5 min by Microsoft's own docs); without explicit `depends_on` — and sometimes a `time_sleep` —
   Terraform races them.
7. **`force_destroy = false` everywhere, and remember that deleting Terraform code destroys
   infrastructure.** Removing a catalog from the config is a destroy, not a no-op. Keep
   `force_destroy_catalog` / `force_destroy_external_location` as variables defaulting to `false`.
8. **Look groups up; don't create them.** `data "databricks_group"` on an Entra-synced group is
   idempotent; `resource "databricks_group"` fights SCIM provisioning and flips between create and
   adopt. Key the group config on the **Entra object ID**, not the display name — display names
   drift, and object IDs are what `external_id` actually wants.
9. **Subnet delegation and the NSG are not optional, and inline subnets beat child resources.**
   Both Databricks subnets need `delegations: [{ serviceName: 'Microsoft.Databricks/workspaces' }]`,
   the NSG with the six `Microsoft.Databricks-workspaces_UseOnly_*` rules, `defaultOutboundAccess:
   false`, and the NAT gateway. Declaring subnets as separate `virtualNetworks/subnets` child
   resources races the parent VNet write — declare them in the VNet's `subnets:` array instead.
10. **ADLS Gen2 is not blob storage to Azure Backup.** A hierarchical-namespace account needs
    `datasourceType: 'Microsoft.Storage/storageAccounts/adlsBlobServices'` and
    `objectType: 'AdlsBlobBackupDatasourceParameters'`, and it has **no operational-tier rule** —
    only the vault-tier rule. The blob variants fail at deploy.
11. **Terraform runs inside `AzureCLI@2` with `addSpnToEnvironment: true`.** That exposes
    `$servicePrincipalId` / `$tenantId` / `$servicePrincipalKey` as **shell** variables — so a
    backend config references them as `$servicePrincipalId`, *not* `$(servicePrincipalId)`. Set
    `auth_type = "azure-cli"` on both Databricks providers and let the CLI session carry the
    identity; don't hand-marshal `ARM_*` variables into a Terraform task.
12. **Keep `terraform plan`/`apply` non-interactive.** `export TF_INPUT=false` (or `-input=false`)
    on every call; otherwise a missing variable silently prompts and the job hangs until timeout.

## Quick symptom → fix index

| Symptom | Likely cause / fix | Reference |
|---|---|---|
| `az deployment sub validate` rejects a parameter | a shared parameter file passes a param this template doesn't declare — declare it unused with a default | plane-architecture-and-naming |
| Lock blocks a property write mid-pipeline | `DeleteRGLock` must run **before** the enable-access stages | network-isolation-and-exposure |
| Locks never recreated after a failed deploy | closing/locking stages need `condition: always()` | azure-devops-pipelines |
| Terraform can't reach the workspace or blob endpoint | firewalls still closed, or the enable stage ran but the plane was re-locked | network-isolation-and-exposure |
| `403` / `AuthorizationPermissionMismatch` creating a storage credential | role assignment not yet propagated — `depends_on` + `time_sleep` | terraform-unity-catalog |
| External location / catalog name already exists | names are metastore-global — prefix with the workspace name | terraform-unity-catalog |
| `credential_name` rejects the storage credential | `data` source `.id` is an internal UUID; pass `.name` (the `resource`'s `.id` *is* the name) | terraform-unity-catalog |
| Grants on a catalog wipe another group's grants | `databricks_grants` (plural) is authoritative — use `databricks_grant` (singular, additive) | terraform-unity-catalog |
| `each.value.workspace_admin` errors on some groups | optional JSON keys need `try(each.value.x, false)` | terraform-unity-catalog |
| Backup vault deploy fails on an HNS account | ADLS needs `adlsBlobServices` + `AdlsBlobBackupDatasourceParameters`, no operational rule | bicep-azure-resources |
| Workspace creation fails on subnets | missing delegation, missing NSG association, or subnets declared as child resources | bicep-azure-resources |
| Private link name doesn't resolve | private DNS zone + VNet link + `privateDnsZoneGroups` — all three are required | bicep-azure-resources |
| Serverless compute can't read the catalog storage | NCC + `databricks_mws_ncc_private_endpoint_rule` (`group_id: blob`) | terraform-unity-catalog |
| Pipeline can't find its variables | variable group name is `{org}-{product}-{branch}`, resolved at **compile** time — one group per environment | azure-devops-pipelines |
| Terraform job hangs with no output | missing `TF_INPUT=false` — it's prompting for a variable | azure-devops-pipelines |
| PSRule passes locally, fails/absent in CI | Bicep needs `AZURE_BICEP_FILE_EXPANSION`; Terraform needs a plan-JSON artifact + `Azure.ExpandTerraformPlan` | azure-devops-pipelines |
| Storage account name invalid / truncated oddly | 24-char limit with no hyphens — `substring(name, 0, min(length(name), 24))` | plane-architecture-and-naming |
| A resource silently disappeared | it was deleted from the Terraform config — deletion *is* destruction | terraform-unity-catalog |

## Commands

```bash
# Bicep: lint (analyzers run as part of build), validate, preview, deploy — all at subscription scope
bicep build bicep/1-network-plane.bicep --outfile /dev/null
az deployment sub validate -n <name> -l <region> -f <template> --parameters @<file> --parameters k=v
az deployment sub what-if   -n <name> -l <region> -f <template> --parameters @<file>
az deployment sub create    -n <name> -l <region> -f <template> --parameters @<file>

# Resource-group locks
az lock create --lock-type CanNotDelete --name DeleteLock --resource-group <rg>
az lock delete --ids "/subscriptions/<sub>/resourceGroups/<rg>/providers/Microsoft.Authorization/locks/DeleteLock"

# Terraform console plane (inside AzureCLI@2 with addSpnToEnvironment: true)
export TF_INPUT=false
terraform init -backend-config="use_oidc=true" -backend-config="client_id=$servicePrincipalId" \
               -backend-config="tenant_id=$tenantId" \
               -backend-config="key=<env>/<region>/<increment>/terraform.tfstate"
terraform plan  -out=main.tfplan -var="workspaceName=..." -var="databricksAccountId=..."
terraform apply main.tfplan
terraform show -json tfplan.binary > terraform-plan.json   # input for PSRule
```

- `az deployment sub validate` catches schema, missing-parameter and allowed-value errors **locally,
  before** touching resources; `what-if` is the review artefact to attach to a pull request.
- Reaching an **authorization** error rather than a schema error means structural validation already
  passed.

## When to use this skill

- Editing a Bicep plane template or a `modules/**` module; adding a subnet, private endpoint,
  storage container, or diagnostic setting.
- Editing the Terraform console plane: catalogs, external locations, grants, groups, NCC.
- Editing the Azure DevOps pipelines: preflight, approval, locks, access toggles, Terraform stages,
  PSRule.
- Debugging ordering, propagation, identity, naming-collision or network-isolation failures.

## Related skills

This skill is the **Azure platform layer**. The layers above it, in order:

- [databricks-asset-bundles](../databricks-asset-bundles/SKILL.md) — `databricks.yml`: the jobs,
  pipelines and Lakebase resources deployed *into* the workspace this skill provisions.
- [develop-sdp](../develop-sdp/SKILL.md) — the declarative pipelines those bundles carry.
- [develop-pyspark](../develop-pyspark/SKILL.md) — the transform code inside them.
- [test-workflows-devops](../test-workflows-devops/SKILL.md) — a much smaller Azure DevOps pipeline
  (lint and test only) if the full preflight/approval/lock/Terraform machinery here is more than you
  need.
- [document-decisions](../document-decisions/SKILL.md) — for the CIDR sizes, retention days,
  redundancy SKUs and timeouts this skill keeps telling you to write a reason for.
