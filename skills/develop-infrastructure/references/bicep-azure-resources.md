# Bicep: the Azure resources behind a VNet-injected Databricks workspace

> **Source.** `[repo]` — module-by-module from a production Bicep codebase (network / control / data
> planes). `[docs]` marks a vendor-documented constraint; `[deduced]` an inference.

## Virtual network and subnets — declare subnets inline

```bicep
resource vnet 'Microsoft.Network/virtualNetworks@2024-07-01' = {
  name: vnetName
  location: location
  tags: tags
  properties: {
    addressSpace: { addressPrefixes: [vnetCidr] }
    subnets: subnets              // the whole array, passed in as a parameter
  }
}

output vnetId string = vnet.id
output subnets array = [for (subnet, i) in subnets: {
  name: subnet.name
  id: vnet.properties.subnets[i].id
}]
```

The repo contains **both** approaches and kept this one. The alternative — a
`Microsoft.Network/virtualNetworks/subnets` child resource per subnet with `parent:` and a chain of
`dependsOn` between them — is in the tree as `workspace-subnets.bicep` and is unused:

- Subnet child resources **race the parent VNet write**: ARM serialises subnet operations on a VNet,
  and concurrent child writes produce `AnotherOperationInProgress` / lost subnets. The chained
  `dependsOn: [previousSubnet]` in that module is the workaround, and it is fragile.
- Declaring the full `subnets:` array makes one atomic VNet write. `[deduced]`
- **Caveat**: a full `subnets:` array is authoritative — a subnet created out-of-band (or by another
  template) is removed on the next deployment. Use the child-resource form only when you must add a
  subnet to a VNet you do not own.
- The output loop maps names to ids positionally. `vnet.properties.subnets[i]` relies on ARM
  returning subnets in the submitted order; prefer `resourceId(...)` construction if you need
  certainty.

### Subnet properties that matter

```bicep
{
  name: workspacePublicSubnetName                       // "container" subnet
  properties: {
    addressPrefix: workspacePublicSubnetCidr
    networkSecurityGroup: { id: workspaceNsg.outputs.nsgId }
    defaultOutboundAccess: false                        // no implicit outbound; NAT GW provides it
    natGateway: { id: workspaceNatGateway.outputs.natGatewayId }
    delegations: [
      { name: 'databricks-del-public', properties: { serviceName: 'Microsoft.Databricks/workspaces' } }
    ]
  }
}
```

- **Both** Databricks subnets need the delegation, the NSG, and the NAT gateway. A differently-named
  delegation on each (`databricks-del-public` / `databricks-del-private`) is required — delegation
  names are unique per subnet, not globally, but keeping them distinct avoids confusion.
- `defaultOutboundAccess: false` turns off Azure's deprecated implicit outbound. Combined with the
  NAT gateway this gives deterministic, single-IP egress — which is what lets a downstream service
  allowlist the platform.
- The private-endpoint subnet takes `privateEndpointNetworkPolicies: 'Disabled'` and **no**
  delegation.
- The data-source subnet (storage private endpoints) needs nothing but an `addressPrefix`.
- A delegated subnet cannot be resized or re-delegated while a workspace is injected. `[docs]`

## The six required NSG rules

Databricks VNet injection requires a specific NSG rule set. When `requiredNsgRules` is
`NoAzureDatabricksRules`, Azure does **not** add them for you — you own them:

| Direction | Name suffix | Protocol | Dest. ports | Source → Destination | Prio |
|---|---|---|---|---|---|
| Inbound | `databricks-worker-to-worker-inbound` | `*` | `*` | VirtualNetwork → VirtualNetwork | 100 |
| Outbound | `databricks-worker-to-databricks-cp` | Tcp | `443`, `8443-8451`, `3306` | VirtualNetwork → `AzureDatabricks` | 100 |
| Outbound | `databricks-worker-to-sql` | Tcp | `3306` | VirtualNetwork → `Sql` | 101 |
| Outbound | `databricks-worker-to-storage` | Tcp | `443` | VirtualNetwork → `Storage` | 102 |
| Outbound | `databricks-worker-to-worker-outbound` | `*` | `*` | VirtualNetwork → VirtualNetwork | 103 |
| Outbound | `databricks-worker-to-eventhub` | Tcp | `9093` | VirtualNetwork → `EventHub` | 104 |

- Each rule is named `Microsoft.Databricks-workspaces_UseOnly_<suffix>`. The prefix is a convention
  Databricks recognises; keep it. `[docs]`
- The destinations are **service tags**, not CIDRs — `AzureDatabricks`, `Sql`, `Storage`, `EventHub`.
  Service tags are region-scoped by Azure automatically.
- `8443-8451` is the control-plane range; `3306` appears twice (control plane and the legacy metastore
  via the `Sql` tag). Omitting `3306` produces clusters that start and then fail on metastore access.
- The one inbound rule plus the matching outbound is worker-to-worker traffic *within* the VNet —
  cluster nodes talk to each other directly.

## NAT gateway + public IP (egress with no public IPs on nodes)

```bicep
resource publicIp 'Microsoft.Network/publicIPAddresses@2024-07-01' = {
  sku: { name: 'Standard' }
  properties: {
    publicIPAddressVersion: 'IPv4'
    publicIPAllocationMethod: 'Static'
    idleTimeoutInMinutes: 4
  }
}

resource natGateway 'Microsoft.Network/natGateways@2024-07-01' = {
  sku: { name: 'Standard' }
  properties: {
    idleTimeoutInMinutes: 4
    publicIpAddresses: [{ id: publicIpId }]
  }
}
```

- `Standard` SKU + `Static` allocation is mandatory for a NAT gateway. `[docs]`
- This is the **complement to secure cluster connectivity**, not a contradiction: `enableNoPublicIp`
  removes public IPs from the *nodes*; the NAT gateway gives those nodes outbound reachability
  through one known address.
- The public IP lives in its own resource group in the repo (`rg-ip-…`), which is why the network
  pipeline unlocks two resource groups. Keep IP resources separate if a network team owns them.
- `idleTimeoutInMinutes: 4` is the minimum; raise it if long-lived outbound connections (e.g. a
  streaming source) are being dropped.

## The Databricks workspace resource

```bicep
resource workspace 'Microsoft.Databricks/workspaces@2025-03-01-preview' = {
  name: workspaceName
  location: location
  sku: { name: 'premium' }                   // trial | standard | premium
  tags: tags
  properties: {
    managedResourceGroupId: managedResourceGroupId
    defaultCatalog: { initialType: 'UnityCatalog' }
    publicNetworkAccess: publicNetworkAccess          // 'Enabled' | 'Disabled'
    requiredNsgRules: requiredNsgRules                // 'AllRules' | 'NoAzureDatabricksRules'
    parameters: {
      storageAccountName:      { value: storageAccountName }     // DBFS root
      storageAccountSkuName:   { value: storageAccountSkuName }
      enableNoPublicIp:        { value: disablePublicIp }        // secure cluster connectivity
      customVirtualNetworkId:  { value: vnetId }
      customPublicSubnetName:  { value: publicSubnetName }
      customPrivateSubnetName: { value: privateSubnetName }
    }
  }
}

output workspaceId  string = workspace.id
output workspaceUrl string = workspace.properties.workspaceUrl
```

Notes that cost time if missed:

- **`parameters:` is a wrapped map** — every value is `{ value: x }`, not `x`. This is an ARM
  workspace-parameters quirk, not normal Bicep.
- `premium` is required for anything access-control related (table ACLs, Unity Catalog governance,
  cluster policies). `standard` silently lacks it.
- `managedResourceGroupId` is a **full resource ID** (`${subscription().id}/resourceGroups/<name>`),
  not a name, and the RG must not already exist. It is also subject to the 90-char RG limit, hence
  the truncation in the naming section.
- `requiredNsgRules: 'NoAzureDatabricksRules'` pairs with SCC (`enableNoPublicIp: true`) and means
  *you* supply the NSG rules above. `AllRules` lets Azure manage the outbound AzureDatabricks rule.
- `defaultCatalog: { initialType: 'UnityCatalog' }` makes a new workspace UC-first instead of
  hive-metastore-first — worth setting explicitly, since the default has changed over API versions.
- `publicNetworkAccess` is the property the pipeline toggles at deploy time (see
  [network-isolation-and-exposure.md](./network-isolation-and-exposure.md)). Keep its *declared*
  value `Disabled` so Bicep re-closes it even if a pipeline failure left it open.
- `-preview` API versions are used deliberately for `defaultCatalog`; pin them, and re-check on
  upgrade — preview property shapes change.
- `workspaceUrl` is only available *after* creation, which is why Terraform reads it through a data
  source rather than receiving it as a Bicep output.

## Private endpoint + private DNS zone (all three parts)

```bicep
resource privateEndpoint 'Microsoft.Network/privateEndpoints@2024-07-01' = {
  properties: {
    subnet: { id: resourceId('Microsoft.Network/virtualNetworks/subnets', vnetName, privateEndpointSubnetName) }
    customNetworkInterfaceName: customNetworkInterfaceName
    privateLinkServiceConnections: [{
      name: privateEndpointName
      properties: {
        privateLinkServiceId: serviceResourceId
        groupIds: [groupId]
      }
    }]
  }
}

resource privateDnsZone 'Microsoft.Network/privateDnsZones@2024-06-01' = if (!empty(privateDnsZoneName)) {
  name: privateDnsZoneName          // e.g. privatelink.azuredatabricks.net
  location: 'global'
}

resource zoneLink 'Microsoft.Network/privateDnsZones/virtualNetworkLinks@2024-06-01' = if (!empty(privateDnsZoneName)) {
  parent: privateDnsZone
  name: '${privateDnsZoneName}-link'
  location: 'global'
  properties: { registrationEnabled: false, virtualNetwork: { id: vnetId } }
}

resource dnsGroup 'Microsoft.Network/privateEndpoints/privateDnsZoneGroups@2021-12-01' = if (!empty(pvtEndpointDnsGroupName)) {
  name: pvtEndpointDnsGroupName     // '<peName>/<groupName>'  — slash-qualified child name
  properties: { privateDnsZoneConfigs: [{ name: 'config1', properties: { privateDnsZoneId: privateDnsZone.id } }] }
}
```

- **Private link needs all three**: the endpoint (gets a VNet IP), the DNS zone + VNet link (so the
  name resolves inside the VNet), and the zone *group* (so the endpoint writes its A record into the
  zone). Missing the group is the classic "endpoint exists, hostname still resolves to the public
  IP" failure.
- `privateDnsZones` and their links are **`location: 'global'`**, always.
- `groupId` per service: `databricks_ui_api` (workspace UI/API), `blob` (ADLS), `vault` (Key Vault),
  `dfs` (ADLS Gen2 filesystem endpoint). A workspace with front-end private link also wants a
  `browser_authentication` endpoint for SSO redirects if the UI is reached privately. `[docs]`
- `resourceId('Microsoft.Network/virtualNetworks/subnets', vnetName, subnetName)` constructs the
  subnet id **without** needing a reference to the VNet resource — useful when the module is scoped
  to the VNet's resource group but doesn't own the VNet.
- The `privateDnsZoneGroups` child name must be `'<privateEndpointName>/<groupName>'`. Writing only
  the group name deploys nothing useful.
- One optional-parameter trick worth reusing: `param privateDnsZoneName string = ''` plus
  `if (!empty(...))` on the three DNS resources makes a single module serve both "endpoint with DNS"
  (the workspace) and "endpoint only, corporate DNS handles records" (storage) cases.
- In this platform the storage private endpoint became **optional** once Unity Catalog accessed
  storage through the access connector + NCC; it is commented out in the data plane with a note.
  Private endpoints and NCC rules solve overlapping problems — decide which one owns storage access
  rather than deploying both by reflex.

## ADLS Gen2 storage account + containers

```bicep
resource storageAccount 'Microsoft.Storage/storageAccounts@2025-01-01' = {
  kind: 'StorageV2'
  sku: { name: skuName }                       // e.g. Standard_GZRS
  properties: {
    accessTier: 'Hot'
    isHnsEnabled: true                         // hierarchical namespace → ADLS Gen2
    supportsHttpsTrafficOnly: true
    minimumTlsVersion: 'TLS1_2'
    publicNetworkAccess: publicNetworkAccess   // 'Disabled' in steady state
    allowBlobPublicAccess: false
    encryption: { services: { blob: { enabled: true }, file: { enabled: true } }, keySource: 'Microsoft.Storage' }
  }
}

resource blobService 'Microsoft.Storage/storageAccounts/blobServices@2025-01-01' = {
  parent: storageAccount
  name: 'default'                              // must literally be 'default'
}

resource containerResources 'Microsoft.Storage/storageAccounts/blobServices/containers@2025-01-01' = [
  for container in containers: {
    parent: blobService
    name: container
    properties: { publicAccess: 'None' }
  }
]
```

- `isHnsEnabled: true` is **immutable after creation** and is what makes the account ADLS Gen2.
  Everything downstream (`abfss://`, the backup-vault datasource type) depends on it. `[docs]`
- The `blobServices` child must be named `default`.
- Container names come from the config JSON, not the template — the container list is the main thing
  that differs between deployment variants, so hard-coding it forces a template edit per variant.
- `publicNetworkAccess` is parameterised with a comment explaining the deploy-time dance; the
  declared value stays `Disabled`.
- `Standard_GZRS` gives geo-zone redundancy; it is `@allowed`-restricted to one value in the repo so
  a cheaper SKU can't be chosen by accident in a higher environment.
- Note the layering decision: **containers used as catalogs are created by Bicep for the fixed
  tiers, but by Terraform for on-demand catalogs** (`azurerm_storage_container` in the shared
  catalogs-grants module). Pick one owner per container or the two tools will fight.

## Data Protection backup vault — the ADLS trap

```bicep
var roleDefinitionId = subscriptionResourceId('Microsoft.Authorization/roleDefinitions',
                                              'e5e2a7ff-d759-4cd2-bb51-3152d37e2eb1')  // Storage Account Backup Contributor
var dataSourceType   = 'Microsoft.Storage/storageAccounts/adlsBlobServices'   // NOT .../blobServices
var resourceType     = 'Microsoft.Storage/storageAccounts'
var vaultTierDefaultRetentionDuration = 'P${vaultTierDefaultRetentionInDays}D'
var repeatingTimeIntervals            = 'R/2024-05-06T${dailyBackupScheduleTime}:00+00:00/P1D'
```

The three things that fail on a hierarchical-namespace account — all three appear as fix commits:

1. **`datasourceTypes` must be `adlsBlobServices`**, not `blobServices`.
2. **`objectType` must be `AdlsBlobBackupDatasourceParameters`**, not
   `BlobBackupDatasourceParameters`, inside
   `policyInfo.policyParameters.backupDatasourceParametersList`.
3. **There is no operational-tier rule for ADLS.** Remove the `AzureRetentionRule` whose
   `sourceDataStore.dataStoreType` is `OperationalStore` and keep only the `VaultStore` one; mark the
   remaining retention rule `isDefault: true`.

Other mechanics:

- The vault needs a **system-assigned identity**, and that identity needs a role assignment on the
  storage account *before* the backup instance is created:
  ```bicep
  resource roleAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
    scope: storageAccount
    name: guid(vault.id, roleDefinitionId, storageAccount.id)     // deterministic, idempotent
    properties: {
      roleDefinitionId: roleDefinitionId
      principalId: reference(vault.id, '2021-01-01', 'Full').identity.principalId
      principalType: 'ServicePrincipal'
    }
  }
  resource backupInstance '...' = { /* ... */ dependsOn: [roleAssignment] }
  ```
  - `guid(...)` of stable inputs is the standard idempotent role-assignment name — redeploying
    produces the same name, so it updates rather than conflicts.
  - `principalType: 'ServicePrincipal'` avoids the "principal not found" race where AAD hasn't
    replicated the new identity yet.
  - The repo uses `reference(vault.id, ..., 'Full').identity.principalId` with
    `vault.identity.principalId` commented beside it — the symbolic form can evaluate before the
    identity exists in some orderings. Prefer the symbolic property; fall back to `reference()` if
    you hit an empty principal id. `[deduced]`
- Schedule format is an **ISO 8601 repeating interval**: `R/<anchor datetime>/<period>`. The anchor
  date is arbitrary and in the past; only the time-of-day and `P1D` matter.
- Retention is an ISO duration built by string concatenation: `'P${days}D'`.
- `softDeleteSettings.state` of `AlwaysOn` is **irreversible**; `On` is reversible; `Off` is what a
  disposable environment needs. Changing `storageSettings[].type` (the redundancy) is rejected once
  the vault has registered backups.
- `backupInstance` name = the storage account name in this design; `friendlyName` is what appears in
  the portal.

## Log Analytics, diagnostics and saved searches

```bicep
resource logAnalytics 'Microsoft.OperationalInsights/workspaces@2025-02-01' = {
  properties: {
    sku: { name: sku }                     // PerGB2018
    retentionInDays: retentionDays         // 7–730; Free is capped at 7
    features: { enableDataExport: true }
  }
}

resource diagnosticSetting 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = {
  name: databricksDiagnosticSettingName
  scope: workspace                         // extension resource: scope = the target
  properties: {
    logAnalyticsDestinationType: null
    logs: [{ category: null, categoryGroup: 'allLogs', enabled: true, retentionPolicy: { days: 0, enabled: false } }]
    metrics: []
    workspaceId: logAnalyticsWorkspaceId
  }
}
```

- A diagnostic setting is an **extension resource**: it takes `scope:` pointing at the monitored
  resource (here an `existing` workspace reference), and lives in that resource's RG.
- `categoryGroup: 'allLogs'` with `category: null` subscribes to every current and future category —
  far better than enumerating categories that change between API versions.
- `retentionPolicy` on a diagnostic setting is deprecated; retention belongs to the Log Analytics
  workspace. Keep it `{ days: 0, enabled: false }`.
- Avoid `listKeys()` outputs. The Log Analytics module in the repo outputs `primarySharedKey` /
  `secondarySharedKey`; module outputs are **recorded in the deployment history in plain text**. If
  a consumer needs the key, read it at the point of use or push it into Key Vault instead. `[deduced]`

### Saved searches from a JSON file

```bicep
var queries = loadJsonContent('./queries.json')

resource savedSearch 'Microsoft.OperationalInsights/workspaces/savedSearches@2025-02-01' = [
  for (item, i) in queries: {
    parent: logAnalytics
    name: guid('${resourceGroup().id}${deployment().name}${i}')
    properties: { category: 'Spark Metrics', displayName: item.displayName, query: item.query, version: 2 }
  }
]
```

- `loadJsonContent()` inlines the file **at compile time**, so the queries ship inside the ARM
  template and need no parameter plumbing. It also means a malformed JSON file fails `bicep build`,
  which is what you want.
- The `guid(...)` name is **seeded with `deployment().name`**, so a differently-named deployment
  creates a *new* set of saved searches rather than updating the old ones. If you want stable,
  updatable searches, seed on something stable (`item.displayName`) instead. `[deduced]`
- The repo ships ~40 Spark observability queries over the `SparkListenerEvent_CL` and
  `SparkMetric_CL` custom tables — stage/task/job latency and throughput, executor CPU/JVM/serialize
  time, shuffle bytes and spill, streaming latency/throughput, and error traces. Those tables are
  populated by the Spark monitoring library, not by the diagnostic setting: shipping the queries is
  useful only if that library is deployed on the clusters. `[deduced]`

## Key Vault

```bicep
resource kv 'Microsoft.KeyVault/vaults@2024-12-01-preview' = {
  properties: {
    tenantId: subscription().tenantId
    enableRbacAuthorization: true
    enableSoftDelete: enableSoftDelete
    softDeleteRetentionInDays: 7
    enablePurgeProtection: true
    accessPolicies: []                      // empty — RBAC owns data-plane access
    sku: { name: 'premium', family: 'A' }
    networkAcls: {
      bypass: 'AzureServices'
      defaultAction: 'Deny'
      ipRules: [ /* ... */ ]
      virtualNetworkRules: [{ id: subnetId }]
    }
  }
}
```

- **`enableRbacAuthorization: true` and `accessPolicies` are mutually exclusive.** With RBAC on,
  access policies are ignored and cannot be modified — the repo keeps a disabled
  `key-vault-add-access-policy` module with exactly this warning in its header. Don't mix the models.
- `enablePurgeProtection: true` is **irreversible** and makes a deleted vault unrecoverable-but-
  unreusable for `softDeleteRetentionInDays`. In disposable environments that permanently burns a
  globally-unique name — parameterise `enableSoftDelete` and keep purge protection off in sandboxes.
- `networkAcls.virtualNetworkRules` requires a **service endpoint** (`Microsoft.KeyVault`) on the
  referenced subnet, not a private endpoint — the mock module adds
  `serviceEndpoints: [{ service: 'Microsoft.KeyVault', locations: ['*'] }]` to the subnet for this.
- `bypass: 'AzureServices'` is what lets ARM template deployment and other first-party services
  through a `defaultAction: Deny` vault.
- Don't commit IP allowlists to a shared repo; parameterise them. Exported portal templates (the
  repo keeps one, fully commented out, under `tests/`) carry tenant ids, subscription ids, object
  ids and emails — sanitise before committing, or keep them out of the repo.

## `bicepconfig.json` — make the linter part of the build

```json
{
  "analyzers": {
    "core": {
      "enabled": true,
      "rules": {
        "no-loc-expr-outside-params": { "level": "warning" },
        "no-hardcoded-env-urls":      { "level": "warning" },
        "use-recent-api-versions":    { "level": "warning" },
        "secure-parameter-default":   { "level": "error" }
      }
    }
  }
}
```

- `bicep build <file> --outfile /dev/null` **runs the analyzers** — that is the entire lint step in
  CI, no extra tool needed. A rule at `level: error` fails the build.
- `secure-parameter-default: error` is the one to keep at error: it blocks a default value on an
  `@secure()` parameter.
- `use-recent-api-versions` at `warning` is pragmatic — it fires constantly as versions age. Review
  it deliberately rather than at every build.
- `no-loc-expr-outside-params` pushes `resourceGroup().location` up into a parameter default, which
  is what makes a template deterministic across scopes.
