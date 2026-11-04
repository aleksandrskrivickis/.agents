# Network isolation vs. the deploy agent: the open→deploy→close pattern

> **Source.** `[repo]` — the design and its fix history in a production Azure Databricks platform.
> `[docs]` marks a vendor-documented behaviour; `[deduced]` an inference.

## The locked-down steady state

Between deployments the platform is closed on five axes:

| Control | Setting | Effect |
|---|---|---|
| Workspace network | `publicNetworkAccess: 'Disabled'` + private endpoint (`databricks_ui_api`) | UI/API reachable only from the VNet |
| Cluster nodes | `enableNoPublicIp: true` (secure cluster connectivity) | nodes have no public IPs; control-plane connection is outbound-initiated |
| Egress | NAT gateway + `defaultOutboundAccess: false` | one known outbound IP, no implicit egress |
| Catalog storage | `publicNetworkAccess: 'Disabled'`, `allowBlobPublicAccess: false` | blob endpoint not reachable from the internet |
| Lifecycle | `CanNotDelete` lock on each resource group | accidental deletion blocked |
| Terraform state storage | `publicNetworkAccess: 'Disabled'` | state blob not reachable from the internet |

Each of those is also the *declared* value in Bicep, so a plane redeploy re-closes anything a failed
run left open. Never change a declared value to `Enabled` to make a pipeline pass.

## Why the agent can't just deploy into it

The Bicep planes are fine: ARM is a public control plane, and `az deployment sub create` only talks
to `management.azure.com`. The **Terraform console plane is not**:

- The `databricks` provider calls the **workspace REST API** at `https://<workspace>.azuredatabricks.net`.
  With `publicNetworkAccess: Disabled`, that hostname is only answerable inside the VNet.
- `azurerm_storage_container` and the external-location validation touch the **blob/dfs endpoint**.
  With the storage firewall closed, so is that.
- `terraform init` needs the **state blob**, on a storage account that is itself locked down.

A Microsoft-hosted or managed-pool agent sits outside the VNet. So the pipeline has to open three
doors, walk through, and close them — and it must close them even when it trips on the way.

## The stage graph

```
Approval
   │
DeleteRGLock                  (networking RG, workspace RG — one job each)
   │
   ├── EnableWorkspaceAccess               (workspace publicNetworkAccess = Enabled)
   │        │
   │        ├── EnableTerraformStateStorageAccess
   │        └── EnableStorageAccess        (catalog storage)
   │                 │
   └─────────────> TerraformDeploy         (init + plan + apply)
                        │
   ┌────────────────────┼────────────────────┐
DisableWorkspaceAccess  DisableStorageAccess  DisableTerraformStateStorageAccess
   │                    │                     │      (all three: condition: always())
   └────────────────────┴─────────────────────┘
                        │
                  CreateRGLock              (condition: always())
```

Four ordering facts, each of which was learned the hard way:

1. **`DeleteRGLock` must come first.** A `CanNotDelete` lock on the resource group blocks the
   property write that flips `publicNetworkAccess`. The repo's original graph had the enable stages
   depend on `Approval` and the unlock happen later; the fix commit is literally *"Fixed rg lock based
   bug preventing interference with public access"*. Unlock, then open.
2. **The two storage opens hang off the workspace open, not off each other.** The history shows this
   reordered twice, with the explicit goal *"run EnableTerraformStateStorageAccess and
   EnableStorageAccess steps before EnableWorkspaceAccess to reduce exposure time to open internet"* —
   and then reverted. The trade-off: serialising reduces each door's open duration but lengthens the
   total window; parallelising shortens the window but opens all three at once. The settled shape
   opens the workspace first (it is the slowest to take effect) and fans out to the two storage
   accounts. There is no universally right answer — make the choice explicit and comment it.
3. **Every closing stage is `condition: always()`** and depends on `TerraformDeploy`. If Terraform
   fails, the doors still close. This is non-negotiable.
4. **`CreateRGLock` fans in from all three closing stages** and is also `condition: always()`. It is
   the run's last act. The repo tried
   `condition: and(always(), not(eq(dependencies.DeleteRGLock.result, 'Skipped')))` to avoid locking
   an RG that was never unlocked, and reverted to plain `always()` — re-locking an already-locked
   group is harmless; leaving production unlocked is not.

## Stateless `azapi` toggle modules

The toggles are **Terraform modules with no backend at all**:

```hcl
# terraform/modules/storage/enable_public_access/main.tf
# Enable public network access on a storage account.
# Stateless — no remote backend; state is ephemeral (local to the agent).

terraform {
  required_providers { azapi = { source = "Azure/azapi" } }
}

resource "azapi_update_resource" "enable_public_access" {
  type        = "Microsoft.Storage/storageAccounts@2023-01-01"
  resource_id = var.storage_account_id
  body = {
    properties = {
      publicNetworkAccess   = "Enabled"
      allowBlobPublicAccess = true
      networkAcls = {
        defaultAction       = "Allow"
        bypass              = "AzureServices"
        virtualNetworkRules = []
        ipRules             = []
        resourceAccessRules = []
      }
    }
  }
}
```

```hcl
# terraform/modules/workspace/disable_public_access/main.tf
resource "azapi_update_resource" "disable_public_access" {
  type        = "Microsoft.Databricks/workspaces@2024-05-01"
  resource_id = var.workspace_id
  body        = { properties = { publicNetworkAccess = "Disabled" } }
}
```

```yaml
# templates/enable-storage-access.yml
- task: AzureCLI@2
  displayName: Enable storage account public access (stateless)
  inputs:
    azureSubscription: ${{ parameters.serviceConnectionName }}
    scriptType: bash
    addSpnToEnvironment: true
    scriptLocation: inlineScript
    inlineScript: |
      set -e
      cd $(System.DefaultWorkingDirectory)/terraform/modules/storage/enable_public_access
      terraform init
      terraform apply -auto-approve -var="storage_account_id=${{ parameters.storageAccountResourceId }}"
```

Why stateless, and why `azapi`:

- **`azapi_update_resource` patches one property of an existing resource** without importing it or
  owning it. `azurerm_storage_account` would require the full resource in state and would fight the
  Bicep template that owns it. This is the right tool for "nudge one property on something another
  system manages". `[docs]`
- **No backend means no state file, no state lock, no drift.** The operation is idempotent: applying
  "Enabled" twice is a no-op. The history shows a version of these modules *with* remote state keys
  (`.../modules/storage/enable_public_access/terraform.tfstate`) that was replaced by the stateless
  form — commit *"Fully stateless storage account public access control"*. Remote state here bought
  nothing and created a lock-contention risk between the enable and disable stages.
- `terraform init` with no backend needs no `-backend-config` and no credentials beyond the CLI
  session. It is fast enough to run four times per pipeline.
- `-auto-approve` is acceptable precisely because the module can only do one thing.
- Four tiny modules (storage enable/disable, workspace enable/disable) instead of one parameterised
  module: each is a single unambiguous action, so a pipeline template can't accidentally pass
  `Disabled` where `Enabled` was meant.
- **The enable module resets `networkAcls` to `defaultAction = "Allow"` with empty rule lists.** That
  is a wide door. The disable module only sets `publicNetworkAccess`/`allowBlobPublicAccess` back —
  it does **not** restore the previous `networkAcls`. If the account had VNet or IP rules, they are
  gone. Either have the disable module restore them explicitly, or (better) keep the steady state
  "closed with no rules" so there is nothing to restore. `[deduced]`

## Propagation delays

Opening a firewall is not instantaneous:

- Storage network-rule changes: **10–60 s typically, up to 5 minutes** per Microsoft's docs. The repo
  carried a plain `sleep 60` in the pipeline after the enable step, and a `time_sleep` resource in the
  Terraform root (tuned 20 s → 60 s) before the storage credential. `[docs]`
- Azure RBAC role assignments: seconds to minutes.
- Both were eventually replaced by proper `depends_on` edges plus **separate pipeline stages**, which
  gives a natural gap: by the time the next stage's agent has started and `terraform init` has run,
  propagation has usually completed.
- If you still need a wait, prefer a `time_sleep` with a `depends_on` (declarative, visible in the
  plan) over a `sleep` buried in a script.

## Why the catalog storage private endpoint became optional

The data plane originally created a `blob` private endpoint for the catalog storage account. It is
now commented out, with the TODO: *"In data plane, cut out private endpoint as Databricks workspace
seems to be able to manipulate storage account via access connector."*

Three overlapping mechanisms can get Databricks to firewalled storage:

| Mechanism | Covers | Needs |
|---|---|---|
| Private endpoint in the workspace VNet | **classic** (VNet-injected) compute | subnet, DNS zone, zone group |
| Access connector + `Storage Blob Data Contributor` | identity/authorisation, not network path | the connector + role assignment |
| NCC + `databricks_mws_ncc_private_endpoint_rule` | **serverless** compute | account-level NCC, endpoint approval |

- The access connector solves *who is allowed*; it does not by itself solve *can packets arrive*.
  With `publicNetworkAccess: Disabled` on storage, a network path is still required.
- **Serverless compute is not in your VNet**, so a VNet private endpoint does nothing for it — that is
  what NCC is for. If the platform runs serverless SQL warehouses or serverless jobs, NCC is
  mandatory and the VNet private endpoint is only for classic compute. `[docs]`
- Deploying all three "to be safe" produces two private endpoints to the same account and two places
  to debug DNS. Decide which compute types you support, then deploy the matching mechanism(s) and
  delete the others.

## Exposure minimisation checklist

- Open the **narrowest** door: a workspace-only operation does not need the catalog storage open.
  The repo opens all three because the console plane touches all three; a grants-only pipeline opens
  only the state storage.
- Keep the open window **inside one stage boundary** where possible — an approval gate in the middle
  of an open window leaves it open for as long as the approver takes lunch. Approve *first*.
- Audit: the toggles are ARM property writes, so they appear in the subscription Activity Log. That is
  the record of who opened what, when.
- Prefer `bypass: 'AzureServices'` + the trusted-services path over a wide-open `defaultAction:
  Allow` where the caller is a first-party Azure service rather than an agent.
- Consider an **IP allowlist** scoped to the agent's egress IP instead of `defaultAction: Allow` — a
  managed pool with a stable outbound address makes this feasible and shrinks the door from
  "everyone" to "one address". `[deduced]`

## The real fix: put the agent inside the VNet

Every door in this document exists because the agent is outside the network. A **self-hosted agent on
a VM or container instance in the workspace VNet** (or a VNet-injected managed pool) removes:

- `EnableWorkspaceAccess` / `DisableWorkspaceAccess`
- `EnableStorageAccess` / `DisableStorageAccess`
- `EnableTerraformStateStorageAccess` / `DisableTerraformStateStorageAccess`
- the propagation sleeps and the `always()` cleanup stages that guard them

…leaving only the lock dance, which is a lifecycle concern rather than a network one. The repo's move
from Microsoft-hosted to a managed pool is a step along that path. If you are designing this fresh,
start with a VNet-resident agent and never build the toggles.

Trade-offs to weigh: a self-hosted agent is infrastructure you patch, scale and secure; the toggles
are code you maintain and a recurring exposure window. For a platform deployed weekly the agent wins;
for one deployed twice a year the toggles may be cheaper. Make the choice explicitly rather than
inheriting it.
