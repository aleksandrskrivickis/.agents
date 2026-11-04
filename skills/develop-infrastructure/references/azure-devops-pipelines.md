# Azure DevOps pipelines for Bicep + Terraform IaC

> **Source.** `[repo]` — from a production Azure DevOps YAML pipeline set (one pipeline per plane,
> plus CI and two shared/on-demand pipelines) and its fix history. `[docs]` marks documented ADO
> behaviour; `[deduced]` an inference.

## Pipeline inventory

| Pipeline | Trigger | What it does |
|---|---|---|
| `ci-pipeline.yml` | push + PR on the sandbox branch, weekly cron | preflight every plane in parallel + PSRule; never deploys |
| `0-mock-infrastructure.yml` | manual | deploys stand-ins for corporate prerequisites (sandbox only) |
| `1-network-plane.yml` | manual | VNet, subnets, NSG, NAT GW |
| `2-control-plane.yml` | manual | workspace, private endpoint, diagnostics |
| `3-data-plane.yml` | manual | storage, containers, backup vault |
| `4-console-plane.yml` | manual | Terraform: Unity Catalog, grants, groups, NCC |
| `shared-catalog-grants-creation.yml` | manual, parameterised | one new catalog + its grants, independent state |
| `shared-global-entra-groups-to-console.yml` | manual | Entra → Databricks account group sync |

Every deploy pipeline is `trigger: none` / `pr: none`. **Infrastructure deployment is manual and
approved; only CI is automatic.** That is the single most important structural decision here.

## The variable group resolved at compile time

```yaml
# templates/variables.yml
variables:
  - name: managedAdoPoolName
    value: Managed-ADO-Pools
  - name: vmImage
    value: ubuntu-22.04
  - name: devopsOrgName
    value: ${{ replace(replace(variables['System.CollectionUri'], 'https://dev.azure.com/', ''), '/', '') }}
  - group: ${{ variables['devopsOrgName'] }}-<product>-${{ variables['Build.SourceBranchName'] }}
```

```yaml
# every pipeline
variables:
  - template: templates/variables.yml
  - name: parametersPath
    value: $(System.DefaultWorkingDirectory)/configuration/parameters.shared.json
```

- The variable group name is **derived**, not written: organisation name (scraped out of
  `System.CollectionUri`) + product slug + branch name. One group per environment, named
  `{org}-{product}-{branch}`, holding `subscriptionId`, `serviceConnectionName`, `environmentName`,
  `deploymentRegion`, `resourceIncrement`, all the computed resource names, `databricksAccountId`,
  `tagChangeNumber` and the three `terraformStateStorage*` values.
- **`${{ }}` is compile-time.** `- group:` is a compile-time construct, so the name *must* be built
  from `${{ }}` template expressions — `$(…)` would not be resolved yet and the group would not be
  found. This is why the branch-to-environment coupling is unavoidable here. `[docs]`
- A missing or unshared group fails the run at **queue time** with a confusing "variable group not
  found". Create the group and grant the pipeline access before first run.
- Mark `subscriptionId`, `databricksAccountId` and anything credential-shaped as **secret** in the
  group. Secret variables are not auto-exported to script environments — pass them explicitly.
- The derived-name trick also makes the repo portable across organisations without an edit.

## Agent pool

```yaml
pool:
  name: $(managedAdoPoolName)
  demands:
    - ImageOverride -equals $(vmImage)
```

- A **managed/self-hosted pool with an `ImageOverride` demand** rather than `vmImage:` on a
  Microsoft-hosted pool. The history shows a switch to hosted agents and a revert: *"Reverting back to
  our own pool as standard DevOps pool did not help…"*.
- This matters for networking: the long-term direction for a private platform is an agent **inside
  the VNet**, which removes the open-the-firewall dance entirely (see
  [network-isolation-and-exposure.md](./network-isolation-and-exposure.md)). A managed pool is the
  stepping stone.
- `ImageOverride -equals <image>` is how an image is selected inside a managed pool; `vmImage:` only
  works for Microsoft-hosted.

## Branch ↔ environment guard

```yaml
# templates/branch-environment-match.yml
steps:
  - task: Bash@3
    displayName: Ensure branch matches environment
    inputs:
      targetType: inline
      script: |
        branch="${BUILD_SOURCEBRANCHNAME//[$'\r\n\t']/}"
        envName="${{ parameters.environmentName }}"
        if [ "${branch}" != "${envName}" ]; then
          echo "##vso[task.logissue type=error]Branch '${branch}' does not match environment '${envName}'"
          exit 1
        fi
```

- This is the **safety interlock**: `environmentName` comes from the variable group (chosen by
  branch), so a mismatch means the group resolution and the branch disagree — i.e. someone is about to
  deploy prod config from a dev branch.
- `${BUILD_SOURCEBRANCHNAME//[$'\r\n\t']/}` strips stray CR/LF — real bugs come from Windows line
  endings in a variable value. `[deduced]`
- `##vso[task.logissue type=error]` surfaces it in the ADO run summary; `exit 1` is what actually
  fails the job. You need both.
- It runs as the **first job of the preflight stage**, so it fails before anything authenticates.

## Preflight: lint, validate, what-if — in parallel

```yaml
# templates/preflight-checks-bicep.yml
jobs:
  - job: BranchEnvironmentMatch
    steps: [ { template: branch-environment-match.yml, parameters: { environmentName: ... } } ]

  - job: Lint
    steps:
      - task: AzureCLI@2
        displayName: Lint Bicep template
        inputs:
          azureSubscription: ${{ parameters.serviceConnectionName }}
          scriptType: bash
          scriptLocation: inlineScript
          inlineScript: |
            bicep build ${{ parameters.templateFilePath }} --outfile /dev/null

  - job: Validate
    steps: [ { template: deployment.yml, parameters: { deployOperation: validate, ... } } ]

  - job: WhatIf
    steps: [ { template: deployment.yml, parameters: { deployOperation: what-if, ... } } ]
```

- **Three independent checks, three jobs, run concurrently** — no `dependsOn`. The history shows job
  dependencies added and then removed; parallel is right because none of them mutate anything.
- `bicep build --outfile /dev/null` is the lint: the Bicep analyzers configured in
  `bicepconfig.json` run during build, so an `error`-level rule fails this job. No separate linter.
- `validate` and `what-if` reuse the **same deployment template** as the real deploy, parameterised by
  `deployOperation`. One code path means the preflight genuinely exercises what will be deployed.
- `what-if` output is the artefact to attach to a pull request.

## The one deployment template

```yaml
# templates/deployment.yml
parameters:
  - name: deployOperation
    type: string
    default: validate
    values: [validate, what-if, create]
  - name: additionalParametersPath
    type: string
    default: ''
  # ...

steps:
  - task: AzureCLI@2
    displayName: Deploy operation (${{ parameters.deployOperation }})
    inputs:
      azureSubscription: ${{ parameters.serviceConnectionName }}
      scriptType: bash
      scriptLocation: inlineScript
      inlineScript: |
        TEMPLATE_NAME=$(basename "${{ parameters.templateFilePath }}" .bicep)
        DEPLOYMENT_NAME="${{ parameters.environmentName }}-${{ parameters.deployOperation }}-${TEMPLATE_NAME}-$(date +%Y%m%d-%H%M%S)"

        COMMAND="az deployment sub ${{ parameters.deployOperation }} \\
          --name \"${DEPLOYMENT_NAME}\" \\
          --location ${{ parameters.deploymentRegion }} \\
          --template-file ${{ parameters.templateFilePath }} \\
          --parameters @${{ parameters.parametersPath }} \\
          --parameters ${{ parameters.additionalBicepParameters }}"

        if [ -n "${{ parameters.additionalParametersPath }}" ]; then
          COMMAND="${COMMAND} --parameters @${{ parameters.additionalParametersPath }}"
        fi

        echo -e "${{ parameters.parametersPath }} contents:\n"; cat ${{ parameters.parametersPath }}
        echo -e "Executing bash:\n${COMMAND}"
        eval "${COMMAND}"
```

- **`values:` on a template parameter is a compile-time allowlist** — a typo'd operation fails at
  queue time, not after authentication.
- **Timestamped deployment names** keep the subscription deployment history readable and avoid
  colliding with a previous run's record (ARM keeps 800 per scope). Encoding env + operation +
  template in the name makes the history self-documenting.
- The `COMMAND` + `eval` construction exists so the optional second parameter file can be appended
  conditionally, and so the exact command is **echoed before execution**. That echo is the single most
  useful debugging affordance in the whole pipeline set — keep it. (`eval` on interpolated values is
  only safe because every input is a template parameter from a trusted variable group; don't extend
  this pattern to user-supplied strings.)
- `cat` of the parameter file in the log makes a wrong-config run obvious at a glance. Never do this
  for a file containing secrets.
- `--parameters` is **repeatable and additive**: a file, then inline `key=value` pairs, then a second
  file. Later values override earlier ones. `[docs]`

### `additionalBicepParameters` — the computed-name bridge

```yaml
variables:
  - name: additionalBicepParameters
    value: >-                       # folded scalar: newlines become spaces
      tagChangeNumber=$(tagChangeNumber)
      deploymentRegion=$(deploymentRegion)
      environmentName=$(environmentName)
      workspaceVnetName=$(workspaceVnetName)
      workspaceVnetCidr=$(workspaceVnetCidr)
      # ... one line per parameter
```

- Every resource **name** and **CIDR** lives in the variable group and is passed inline. The Bicep
  defaults exist for local runs; the variable group is the source of truth in CI.
- `>-` (folded, strip final newline) is what turns a readable multi-line list into the single
  space-separated string `az` needs. `|-` would keep the newlines and break the command.
- The downside is real: this list must be maintained per plane, and CI keeps a *second* copy
  (`additionalBicepParameters<Plane>`). When adding a parameter, grep for every occurrence — the
  history has several "Added missing variables" commits.

## Approval gate

```yaml
  - stage: Approval
    displayName: Approval
    jobs:
      - deployment: WaitForApproval
        environment: $(environmentName)
        strategy:
          runOnce:
            deploy:
              steps:
                - script: echo "Approval granted, proceeding with deployment"
```

- A no-op `deployment:` job bound to an **ADO environment** is the idiomatic manual gate: the approval
  checks are configured on the *environment*, not in YAML, so changing approvers needs no code change.
- `environment: $(environmentName)` means each environment carries its own approver list.
- Put it **after** preflight and **before** anything mutating. In the console plane it also gates the
  lock deletion, so an unapproved run cannot even unlock a resource group.

## Resource-group locks

```yaml
# templates/lock-create.yml
inlineScript: |
  az lock create --lock-type CanNotDelete --name DeleteLock --resource-group ${{ parameters.resourceGroupName }}

# templates/lock-delete.yml
inlineScript: |
  az lock delete --ids "/subscriptions/${{ parameters.subscriptionId }}/resourceGroups/${{ parameters.resourceGroupName }}/providers/Microsoft.Authorization/locks/DeleteLock"
```

```yaml
  - stage: DeleteRGLock
    jobs:
      - job: RGNetworking
        steps: [ { template: templates/lock-delete.yml, parameters: { resourceGroupName: $(rgNetworkingName) } } ]
      - job: RGIP
        steps: [ { template: templates/lock-delete.yml, parameters: { resourceGroupName: $(rgIpName) } } ]

  # ... Deploy ...

  - stage: CreateRGLock
    condition: always()            # re-lock even when the deploy failed
    jobs: [ ... same two jobs with lock-create ... ]
```

- **One job per resource group**, so the two unlocks run in parallel and a failure is attributable.
- `az lock delete --ids <full resource id>` is used instead of `--name … --resource-group …` because
  the `--ids` form does not fail when the lock is absent in the same way, and it is unambiguous about
  scope. `[deduced]`
- **`condition: always()` on `CreateRGLock` is the important bit** — otherwise a failed deploy leaves
  the platform unlocked. The history contains a deliberate experiment with
  `condition: and(always(), not(eq(dependencies.DeleteRGLock.result, 'Skipped')))` (don't re-lock if
  the unlock never ran) which was **reverted to plain `always()`**: re-locking an already-locked RG is
  harmless, leaving prod unlocked is not. Prefer the blunt version.
- Locks are `CanNotDelete`, not `ReadOnly`. `ReadOnly` blocks tag and property writes and would break
  every deployment.
- **Locks block the public-access toggle too.** Ordering is covered in
  [network-isolation-and-exposure.md](./network-isolation-and-exposure.md): unlock *first*, then open.

## Terraform inside `AzureCLI@2`

```yaml
  - task: AzureCLI@2
    displayName: Terraform Init, Plan & Apply
    inputs:
      azureSubscription: $(serviceConnectionName)
      scriptType: bash
      addSpnToEnvironment: true          # exposes $servicePrincipalId / $servicePrincipalKey / $tenantId
      scriptLocation: inlineScript
      inlineScript: |
        set -e
        export TF_INPUT=false
        cd $(System.DefaultWorkingDirectory)/terraform
        terraform init $(terraformBackendConfig) -backend-config="key=$(environmentName)/$(deploymentRegion)/$(resourceIncrement)/terraform.tfstate"
        terraform plan -out=main.tfplan $(terraformVariables)
        terraform apply main.tfplan
```

```yaml
variables:
  - name: terraformBackendConfig
    value: >-
      -backend-config="resource_group_name=$(terraformStateStorageRgName)"
      -backend-config="storage_account_name=$(terraformStateStorageAccName)"
      -backend-config="container_name=$(terraformStateStorageAccContainerName)"
      -backend-config="subscription_id=$(subscriptionId)"
      -backend-config="use_oidc=true"
      -backend-config="client_id=$servicePrincipalId"
      -backend-config="tenant_id=$tenantId"
```

Five things to get right:

1. **`$servicePrincipalId` and `$tenantId` are SHELL variables, not pipeline variables.**
   `addSpnToEnvironment: true` puts them in the script's environment; `$(servicePrincipalId)` would
   be an unresolved pipeline variable. The `$(…)` forms in the same string *are* pipeline variables.
   Mixing both in one value is correct and deliberate here — read it carefully before editing.
2. **`use_oidc=true`** means workload identity federation: no storage account key, no SAS. The
   service connection's federated credential authenticates to the backend. Nothing secret is written
   into the pipeline.
3. **`export TF_INPUT=false`** (or `-input=false` per command). Without it a missing variable prompts
   and the job hangs to timeout. Both forms appear in the repo as fixes.
4. **`set -e`** so a failed `init` doesn't fall through to `plan`.
5. **`plan -out` then `apply <planfile>`** — apply the reviewed plan, not a fresh one.

### State key layout

```
$(environmentName)/$(deploymentRegion)/$(resourceIncrement)/terraform.tfstate
$(environmentName)/.../$(terraformModuleLocation)/terraform.tfstate
$(environmentName)/.../$(terraformModuleLocation)/${{ parameters.catalogName }}/terraform.tfstate
```

Environment, region and increment first — then the module path, then the per-instance discriminator.
One naming rule, and a new standalone module needs no new container or storage account.

### `terraformVariables`

```yaml
  - name: terraformVariables
    value: >-
      -var="tagChangeNumber=$(tagChangeNumber)"
      -var="workspaceName=$(workspaceName)"
      -var="databricksAccountId=$(databricksAccountId)"
      -var="accessConnectorName=ac-uc-dbw-$(environmentName)-uks-$(resourceIncrement)"
      -var="deploymentType=${{ parameters.deploymentType }}"
      -var='catalogGroups=${{ convertToJson(parameters.catalogGroups) }}'
```

- **`convertToJson()`** turns a pipeline `type: object` parameter into a Terraform `map(string)`.
  Note the **single quotes** around that `-var` — the JSON contains double quotes.
- `${{ parameters.x }}` (compile-time, from the runtime-parameters form) and `$(x)` (runtime, from
  the variable group) coexist in one string. Only `${{ }}` can be used where the value must be known
  before the run starts.
- Names assembled inline (`ac-uc-dbw-…`) duplicate the Bicep naming construct in YAML. It works, but
  it is a third copy of the convention — prefer putting the computed name in the variable group.

## Runtime parameters for on-demand pipelines

```yaml
parameters:
  - name: deploymentType
    displayName: "Deployment type (client or internal)"
    type: string
    default: internal
    values: [client, internal]
  - name: catalogName
    displayName: "Catalog name. Use `client-<name>` for tenant catalogs."
    type: string
    default: "client-test"
  - name: catalogGroups
    displayName: "Map of AD group names to privilege levels (ordinary, elevated, all)"
    type: object
    default:
      SG-dbx-ws-datateam: all
      SG-dbx-bronze-admins: ordinary
```

- `parameters:` at pipeline level renders a **queue-time form**. `values:` becomes a dropdown;
  `type: object` becomes a YAML editor.
- `displayName` is the only documentation the operator sees — spend words there, including the naming
  convention they must follow.
- This is how "create a catalog for a new tenant with these groups" becomes a self-service pipeline
  rather than a pull request.

## CI pipeline

```yaml
trigger: { batch: true, branches: { include: [sandbox] } }
pr:      { branches: { include: [sandbox] } }
schedules:
  - cron: "30 9 * * 1"
    displayName: Weekly Monday 09:30
    branches: { include: [sandbox] }
    always: true

stages:
  - stage: PreflightCheckNetworkPlane
    dependsOn: []            # explicit empty → runs immediately, in parallel
    jobs: [ { template: templates/preflight-checks-bicep.yml, parameters: {...} } ]
  # ... one stage per plane ...
  - stage: PSRuleBicepAnalysis
    dependsOn: []
  - stage: PSRuleTerraformAnalysis
    dependsOn: [PreflightCheckConsolePlane]     # needs the plan JSON artifact
```

- **`dependsOn: []` is not the same as omitting `dependsOn`.** Omitted means "depend on the previous
  stage" (sequential); `[]` means "no dependencies" (parallel from the start). Every independent check
  gets `[]`. `[docs]`
- `batch: true` coalesces pushes so a burst of commits produces one run.
- `always: true` on the schedule runs it even with no changes — it catches *drift and API
  deprecation*, not just code changes. That is the real value of a weekly IaC CI run.
- The mock-infrastructure stage is gated:
  `condition: eq(variables['Build.SourceBranchName'], 'sandbox')`.
- **CI never deploys.** It validates and previews. The equivalent discipline for Terraform is
  plan-only; note the repo's `preflight-checks-terraform.yml` does `apply` the *stateless access
  toggles* (it must, to be able to plan the main config) and only `plan`s the main configuration.
  Keep that distinction deliberate and narrow.

## PSRule static analysis

```yaml
# .ps-rule/ps-rule.yaml
requires: { PSRule: ">=2.9.0" }
input:
  pathIgnore: [".github/", "pipelines/", "docs/", "*.md"]
  format: File
include:
  module: [PSRule.Rules.Azure]
convention:
  include: ["Azure.ExpandTerraformPlan"]
configuration:
  AZURE_PARAMETER_FILE_EXPANSION: true
  AZURE_BICEP_FILE_EXPANSION: true
  AZURE_BICEP_FILE_EXPANSION_TIMEOUT: 60
  AZURE_TERRAFORM_EXPAND: true
  AZURE_TERRAFORM_PLAN_FILE_EXPANSION: true
output:
  culture: ["en-GB"]
rule:
  exclude: []
```

```yaml
# Bicep: point it at the source tree
- task: ps-rule-assert@2
  inputs:
    inputPath: bicep/
    modules: PSRule.Rules.Azure
    option: $(System.DefaultWorkingDirectory)/.ps-rule/ps-rule.yaml
    outputFormat: NUnit3
    outputPath: $(Common.TestResultsDirectory)/psrule-results.xml
  continueOnError: true

- task: PublishTestResults@2
  condition: succeededOrFailed()
  inputs:
    testResultsFormat: NUnit
    testResultsFiles: "psrule-results.xml"
    searchFolder: $(Common.TestResultsDirectory)
    failTaskOnFailedTests: true
    failTaskOnMissingResultsFile: true
```

- **`AZURE_BICEP_FILE_EXPANSION: true` is what makes PSRule understand Bicep at all** — it compiles
  the templates first. Without it, `.bicep` files are skipped and the stage passes vacuously.
  `AZURE_PARAMETER_FILE_EXPANSION` does the same for parameter files.
- **Terraform needs a plan, not source.** Export it in the preflight job and publish it:
  ```yaml
  terraform show -json tfplan.binary > $(Build.ArtifactStagingDirectory)/terraform-plan.json
  ```
  then download the artifact in the PSRule job and pass `conventions: "Azure.ExpandTerraformPlan"`.
  This is why `PSRuleTerraformAnalysis` is the only CI stage with a `dependsOn`.
- **`continueOnError: true` + `failTaskOnFailedTests: true`** is the idiom: let the analysis finish
  and publish results, then fail the build from the *test publish* step. Reversing this loses the
  report on failure.
- `failTaskOnMissingResultsFile: true` catches the silent case where the analyser produced nothing —
  the most common PSRule-in-CI failure mode.
- `NUnit3` output turns rule failures into the ADO **Tests** tab, with history and trend.
- The repo's own TODO records that the Terraform half is fragile and names
  **Checkov / Terrascan / tfsec** as alternatives. PSRule's Azure rules are strongest on ARM/Bicep;
  for Terraform, a Terraform-native scanner is a reasonable second tool rather than a replacement.
- `rule: { exclude: [] }` — keep the empty list present as the documented place to put a waiver, so
  waivers land in one reviewable spot.

## Stage dependency patterns worth reusing

```yaml
  - stage: X
    dependsOn: []                                   # parallel from the start
  - stage: Y
    dependsOn: [A, B]                               # fan-in
  - stage: Z
    condition: always()                             # cleanup / re-lock / re-close
  - stage: W
    condition: eq(variables['Build.SourceBranchName'], 'sandbox')   # branch-gated stage
```

- Cleanup stages (`Disable*Access`, `CreateRGLock`) are `condition: always()` and `dependsOn` the
  stage they clean up after.
- A final fan-in stage that depends on **all** the cleanup stages is how the run's last act is
  re-locking:
  ```yaml
  - stage: CreateRGLock
    dependsOn: [DisableWorkspaceAccess, DisableStorageAccess, DisableTerraformStateStorageAccess]
    condition: always()
  ```
- Jobs within a stage are parallel by default; stages are sequential by default. That asymmetry is the
  source of most "why did this run first" confusion.

## Logging and secret-handling notes

- `##vso[task.logissue type=error]Message` — surfaces an error in the run summary.
- `##vso[task.setvariable variable=X;issecret=true]value` — sets a masked variable for later steps.
  The repo used this to bridge SPN credentials into a Terraform task and later removed the need for
  it; if you find yourself reaching for it to pass credentials, prefer `addSpnToEnvironment` + CLI
  auth instead.
- Echoing a command before `eval` is good; echoing a parameter file is good **only** when it holds no
  secrets. Keep secrets in the variable group marked secret, and out of config JSON.
