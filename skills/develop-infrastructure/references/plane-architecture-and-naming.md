# Plane architecture, naming, tagging & configuration

> **Source.** Everything here is `[repo]` — observed in a production Azure Databricks platform IaC
> repository (Bicep + Terraform + Azure DevOps) and its ~700-commit history. Items marked
> `[deduced]` are inferences from that code; `[docs]` marks a vendor-documented constraint the repo
> relies on.

## Why four planes

A single `main.bicep` was split into three Bicep plane templates plus a Terraform plane. The driver
was not elegance — it was **blast radius and iteration speed**:

| Plane | Tool | Owns | Changes… |
|---|---|---|---|
| 1 Network | Bicep | VNet, subnets, NSG, NAT gateway, public IP | rarely; shared with other platforms |
| 2 Control | Bicep | Databricks workspace, private endpoint, diagnostics | rarely; recreation is disruptive |
| 3 Data | Bicep | ADLS Gen2 account, containers, backup vault | occasionally (new container/tier) |
| 4 Console | Terraform | Unity Catalog, grants, groups, NCC | constantly |

The console plane changes orders of magnitude more often than the network plane, and it is the only
layer whose provider (Databricks) is not ARM. Splitting it off means a grant change does not require
re-validating a VNet.

### Planes are independent, not chained

`main.bicep` composes all three with `dependsOn`, but each plane template is **also a standalone
subscription-scope deployment** that re-reads what it needs:

```bicep
targetScope = 'subscription'

resource rgNetworking 'Microsoft.Resources/resourceGroups@2025-04-01' existing = {
  name: workspaceVnetRgName
}

resource workspaceVnet 'Microsoft.Network/virtualNetworks@2024-07-01' existing = {
  name: workspaceVnetName
  scope: resourceGroup(rgNetworking.name)
}
```

Consequences worth knowing:

- A plane can be redeployed alone, in any order, without the earlier planes' outputs.
- The cost is **name coupling**: the control plane must *compute the same VNet name* the network
  plane computed. That is why the naming construct (below) is duplicated verbatim in every template
  rather than passed as an output.
- `existing =` resources are resolved at deploy time, so a missing prerequisite surfaces as a
  *runtime* "not found", not a validation error. `what-if` catches it earlier than `create`.

## Subscription-scope Bicep

Every plane template is `targetScope = 'subscription'`, which means:

- Resource groups are *created in the template* (`Microsoft.Resources/resourceGroups`), not assumed.
- Every module needs an explicit `scope: resourceGroup(<name>)`.
- Deploy with `az deployment sub create/validate/what-if --location <region>` — `--location` is
  required at subscription scope even though the RGs carry their own locations (it names where the
  *deployment metadata* lives). `[docs]`
- `resourceGroup()` inside a module refers to the module's scope, not the template's — so
  `resourceGroup().name` in a module is the target RG, which is how the saved-search module gets its
  own RG id for a `guid()` seed.

## Naming convention

```bicep
param genericNamingConventionConstruct            string = '${environmentName}-${substring(deploymentRegion, 0, 3)}-${resourceIncrement}'
param genericNamingConventionConstructAlternative string = '${environmentName}${substring(deploymentRegion, 0, 3)}${resourceIncrement}'
```

Pattern: `{resource-type}-{workload}-{environment}-{region}-{increment}` → e.g. `vnet-dbw-dev-uks-001`.

- `substring(deploymentRegion, 0, 3)` turns `uksouth` → `uks`. It is a *prefix* slice, so `ukwest`
  also becomes `ukw` only by luck of the first three characters — validate the `@allowed` list
  against the slice when adding regions. `[deduced]`
- `resourceIncrement` (`001`, `ss1`, …) exists so **two independent platforms can coexist in the
  same environment and region**. Thread it through everything or the second deployment collides.
- The **Alternative** (hyphen-free) construct exists purely for resources that forbid hyphens —
  storage accounts. Keep both; don't `replace()` at each use site.

### Length limits are real and need truncation

```bicep
// storage account: 3–24 chars, lowercase alphanumeric only
param catalogSAName string = 'sadbw${genericNamingConventionConstructAlternative}'
param catalogStorageAccountName string = substring(catalogSAName, 0, min(length(catalogSAName), 24))

// managed resource group: 90 chars
param workspaceManagedRgConstruct string = 'rg-${workspaceName}-managed'
param workspaceManagedRgName string = substring(workspaceManagedRgConstruct, 0, min(length(workspaceManagedRgConstruct), 90))
```

- The `min(length(x), n)` guard is what makes `substring` safe — `substring(x, 0, 24)` **throws** when
  `x` is shorter than 24. Always pair them.
- Key Vault is also 24 chars and **globally unique**, which is why the repo's vault name deviates
  from the otherwise-consistent convention. Expect naming exceptions wherever the namespace is
  global (storage accounts, key vaults, Databricks serving endpoints).
- `@minLength(3) @maxLength(24)` on the *input* param plus the truncation on the *derived* param is
  belt-and-braces: the decorator catches a bad hand-passed value; the truncation catches a long
  generated one.

## Tagging: config ∪ runtime

```bicep
@description('Tags coming from configuration JSON (e.g. per-environment defaults).')
param tagsConfig object = {}

@description('Tags injected at deployment runtime (e.g. pipeline variables). These override configuration tags.')
param tagsRuntime object = {
  Environment: environmentName
  ChangeNumber: tagChangeNumber
}

var tags = union(tagsConfig, tagsRuntime)
```

- `union()` on objects is a **right-biased merge** — later arguments win. That is the whole mechanism:
  the JSON config carries slow-moving governance tags, the pipeline injects per-run values. `[docs]`
- `tagsConfig object = {}` (with a default) rather than a required param: CI validates templates
  without the parameter file in some stages, and a required object fails the lint. This exact change
  appears in the history as a fix.
- Mandatory governance tag set observed: `BauStatus` (BAU/Project), `BauStatusUpdate` (the date the
  Project tag flips to BAU), `ChangeNumber`, `CreatedBy`, `CreatedDate`, `Product`, `OperationsTeam`,
  `ServiceTier`, `Environment`. Constrain the enumerable ones with `@allowed`.
- Tags do **not** propagate to child resources in ARM. Every module takes `tags object` and sets it
  on every resource it creates. Grep for a resource without `tags:` — it is almost always a bug.
- Databricks Unity Catalog objects can't carry Azure tags, so the repo smuggles them into the
  external location's `comment`:
  ```hcl
  comment = "Tags:\n\n${join("\n", [for k, v in var.tags : "${k}: ${v}"])}"
  ```

## Configuration as JSON, not as Bicep/HCL

Four config files, read by *both* toolchains:

| File | Shape | Read by |
|---|---|---|
| `parameters.shared.json` | ARM parameter file — `parameters.tagsConfig.value` | Bicep (`--parameters @file`) **and** Terraform (`jsondecode(file(...))`) |
| `parameters.<deploymentType>.json` | ARM parameter file — the container list per variant | Bicep (second `--parameters @file`) and Terraform |
| `grants.<deploymentType>.json` | `{ "<group>": { privileges: [...], containers: [...] } }` | Terraform only |
| `groups.global.json` | `{ "<group>": { entra_object_id, workspace_admin?, account_admin? } }` | Terraform only |

Why ARM-parameter-file shape for the shared ones: so Bicep can consume them directly with
`--parameters @…` while Terraform reaches in through the envelope:

```hcl
shared_config = jsondecode(file("${path.module}/../configuration/parameters.shared.json"))
tags = merge(local.shared_config.parameters.tagsConfig.value, { ChangeNumber = var.tagChangeNumber })
```

- `local.<x>.parameters.<y>.value` is the price of reusing the ARM envelope. Accept it rather than
  keeping two copies of the tag list.
- `path.module`-relative paths are **depth-coupled to where the module lives**. Moving a module one
  directory deeper silently breaks `${path.module}/../../../../configuration/...`; the history
  contains exactly this bug ("Fix file path bug", "Configuration path correction"). When relocating a
  Terraform module, re-count the `../` segments.

### The `deploymentType` variant switch

A single runtime parameter (`internal` | `client`) selects *which* config files load, in both
toolchains:

```yaml
# pipeline
parameters:
  - name: deploymentType
    type: string
    default: internal
    values: [client, internal]
variables:
  - name: additionalParametersPath
    value: $(System.DefaultWorkingDirectory)/configuration/${{ parameters.deploymentType }}.parameters.json
```

```hcl
# terraform
grants_config     = jsondecode(file("${path.module}/../configuration/grants.${var.deploymentType}.json"))
additional_config = jsondecode(file("${path.module}/../configuration/parameters.${var.deploymentType}.json"))

variable "deploymentType" {
  default = "internal"
  validation {
    condition     = contains(["client", "internal"], var.deploymentType)
    error_message = "deploymentType must be 'client' or 'internal'."
  }
}
```

Mirror the pipeline's `values:` list in a Terraform `validation` block — the pipeline constrains the
UI, the validation constrains a local run.

## The shared-parameter-file trick (and its tax)

All planes are deployed with the **same** `parameters.shared.json`. ARM rejects a parameter file key
that the template does not declare, so each template declares the ones it doesn't use:

```bicep
// This unused parameter is declared to allow usage of control plane with the same set of
// parameters as other planes in CI.
@description('Catalog storage containers (declared here to accept the shared parameter file; not used in this template).')
param catalogStorageAccountContainers array = []
```

- Keep the comment. Without it, the next person deletes the "dead" parameter and breaks CI.
- The alternative — one parameter file per plane — was rejected because the tag block would then be
  duplicated four times and drift.
- Inline `--parameters key=value` pairs are additive on top of the file, and that is where every
  computed name goes (see [azure-devops-pipelines.md](./azure-devops-pipelines.md) →
  `additionalBicepParameters`).

## Mock infrastructure for isolated testing

The platform normally plugs into pre-existing corporate infrastructure (a shared VNet, a shared Log
Analytics workspace, a shared Key Vault). To deploy into an empty sandbox subscription, a
`tests/mock-resources.bicep` module **creates stand-ins for those prerequisites**, gated by a single
flag:

```bicep
var isolatedTestEnvironmentScenario bool = true   // true when the prerequisites don't exist yet

module mockResources 'tests/mock-resources.bicep' = if (isolatedTestEnvironmentScenario) {
  name: 'mock-resources'
  params: { /* vnet, log analytics, key vault, the three resource groups */ }
}

// Every 'existing' prerequisite then conditionally waits for the mocks:
resource logAnalyticsWorkspace 'Microsoft.OperationalInsights/workspaces@2025-02-01' existing = {
  name: logAnalyticsWorkspaceName
  scope: resourceGroup(rgSharedServices.name)
  dependsOn: isolatedTestEnvironmentScenario ? [mockResources] : []
}
```

Patterns worth copying:

- **`dependsOn: <flag> ? [mockModule] : []`** — a conditional dependency array. This is how an
  `existing =` reference is made to wait for a resource that may or may not be created in the same
  deployment. Bicep has no `dependsOn` on conditional modules otherwise.
- The flag also **relaxes settings that cannot work in a sandbox**:
  ```bicep
  workspacePublicNetworkAccess: isolatedTestEnvironmentScenario ? 'Enabled' : workspacePublicNetworkAccess
  catalogStorageAccountBackupVaultSoftDeleteSetting: isolatedTestEnvironmentScenario ? 'Off' : <configured>
  ```
  Soft delete `Off` matters: with soft delete **On**, a torn-down sandbox leaves undeletable vaults
  and name collisions on the next run. Likewise Key Vault purge protection is irreversible — a
  sandbox vault with purge protection permanently burns its globally-unique name.
- The mock pipeline is gated to the sandbox branch only:
  `condition: eq(variables['Build.SourceBranchName'], 'sandbox')`.
- Keep mocks under `bicep/tests/` and exclude that path from static analysis input if the rules are
  tuned for production resources.

## Branch = environment

The repo runs one long-lived branch per environment (`sandbox`, `dev`, `fiat`, `prod`), and every
pipeline asserts the match before doing anything (see
[azure-devops-pipelines.md](./azure-devops-pipelines.md) → branch guard). Implications:

- `environmentName` is `@allowed(['sandbox','dev','fiat','prod'])` in every template, so a typo fails
  at validate rather than creating `rg-dbw-dve-uks-001`.
- Promotion is a merge, which means **config and code promote together** — a grant added on `dev`
  reaches `prod` only via the merge.
- Shared, cross-environment pipelines (global Entra groups) do not fit this model. The repo's
  interim answer is a hard branch check that rejects every branch but one, with a TODO to move them
  to a dedicated `shared` branch. If you have cross-environment resources, plan their home early.

## VNet address-space planning for VNet injection

```
vnet  10.x.y.0/24                                    256 addresses
  DataSourceSubnet                      /29           8    private endpoints to storage/data
  DatabricksWorkspacePrivateEndPointSubnet /27       32    private endpoint to the workspace
  DatabricksWorkspaceContainerSubnet    /28          16    "public"  (container) — delegated
  DatabricksWorkspaceHostSubnet         /28          16    "private" (host/VM) — delegated
```

- The container and host subnets **must be the same size** and are the ones that bound cluster size:
  usable IPs ≈ half the subnet (each node consumes an address in *both*). `[docs]`
- Microsoft recommends **/26 minimum** for the Databricks subnet pair; smaller works but caps max
  nodes. The repo documents its own tension here: a /28 pair fits the space it was given but is below
  the recommendation. Size this before deployment — **the delegated subnets cannot be resized once a
  workspace is injected into them**. `[docs]`
- Azure reserves 5 addresses per subnet, so a /29 is 3 usable — fine for a couple of private
  endpoints, not for growth.
- The private-endpoint subnet needs `privateEndpointNetworkPolicies: 'Disabled'`; the delegated
  subnets must **not** host private endpoints.
- Plan the host/container pair at the *end* of the address space and the small service subnets at the
  start — that leaves the contiguous middle free for later subnets.
