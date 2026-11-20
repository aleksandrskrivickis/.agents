# Build the scaffold: a complete, ordered recipe

> **Source.** `[repo]` — reproduces a shipped Azure IaC hiring test, with the seven harness defects
> from [harness-and-fairness.md](./harness-and-fairness.md) **corrected**. Every divergence from the
> original is listed in [Divergences](#divergences-from-the-source-scaffold) so you can revert any
> of them deliberately. `[docs]` marks vendor-documented behaviour.

This file is the build order. Work top to bottom and the repository is complete and verifiable at
the end. Read [exercise-design.md](./exercise-design.md) first if you want to know *why* any of it
is shaped this way — none of the reasoning is repeated here.

## 0. Decisions to make before writing a file

Fix these five, because they are threaded through every file below:

| Decision | Source scaffold | Change it when |
|---|---|---|
| `NAME_PREFIX` | `iactest` (3–10 lowercase alphanumeric) | Always — it is also the RG suffix (`rg-<prefix>`) and must not collide with a real workload |
| Region | `westeurope` | Your sandbox is elsewhere; Cosmos free tier and some SKUs are region-bound |
| Tracks offered | Bicep, Terraform, ARM | Drop ARM unless you need to assess it — see [the ARM track](#5c-the-arm-track-optional) |
| Time-box | 2–4 hours | You change the module count; five modules is what makes 2–4 hours real |
| Does Checkov gate? | No (advisory) | You are willing to fix the scaffold's own findings first |

Then create the tree. Empty module folders carry a `.gitkeep` so they survive the clone:

```
.
├── .devcontainer/{devcontainer.json,post-create.sh}
├── .github/workflows/lint.yml
├── .gitignore
├── README.md                     # the candidate-facing brief
├── infra/
│   ├── README.md
│   ├── bicep/{main.bicep,main.bicepparam,bicepconfig.json}
│   ├── bicep/modules/{network,private-dns,keyvault,cosmosdb,webapp}/.gitkeep
│   ├── terraform/{main.tf,variables.tf,outputs.tf,versions.tf}
│   ├── terraform/modules/{network,private-dns,keyvault,cosmosdb,webapp}/.gitkeep
│   └── arm/{azuredeploy.json,azuredeploy.parameters.json}          # optional track
│       └── modules/{network,private-dns,keyvault,cosmosdb,webapp}/.gitkeep
└── scripts/{bicep.sh,terraform.sh,arm.sh}
```

```bash
for tech in bicep terraform arm; do
  for m in network private-dns keyvault cosmosdb webapp; do
    mkdir -p "infra/$tech/modules/$m" && touch "infra/$tech/modules/$m/.gitkeep"
  done
done
```

## 1. The module interface — write this down once

Every track's root must declare the **same** five contracts, or the tracks are not comparable. This
table is the single source of truth; the roots below implement it.

| Module | Inputs | Outputs the root consumes |
|---|---|---|
| `network` | `location`, `namePrefix`, `tags` | `vnetId`, `webSubnetId`, `peSubnetId` |
| `private-dns` | `namePrefix`, `vnetId`, `tags` | `keyVaultZoneId`, `cosmosZoneId` |
| `keyvault` | `location`, `namePrefix`, `peSubnetId`, `privateDnsZoneId`, `tags` | `name`, `id` |
| `cosmosdb` | `location`, `namePrefix`, `peSubnetId`, `privateDnsZoneId`, `tags` | `accountName`, `id` |
| `webapp` | `location`, `namePrefix`, `webSubnetId`, `keyVaultName`, `cosmosAccountName`, `tags` | `defaultHostname` |

Dependency order falls out of it: `network` → `private-dns` → (`keyvault`, `cosmosdb`) → `webapp`.

## 2. `.gitignore`

```gitignore
# Terraform
.terraform/
*.tfstate
*.tfstate.*
.terraform.tfstate.lock.info
crash.log
crash.*.log
*.tfvars
*.tfvars.json
override.tf
override.tf.json
*_override.tf
*_override.tf.json
.terraformrc
terraform.rc

# Plan output — the scripts write infra/terraform/tfplan.bin.
# MUST be active, not a commented example: the harness creates this file and the
# rubric marks candidates down for committing state. (FIX 7)
*tfplan*

# Azure / tooling
.azure/
*.decompiled.bicep
```

> **Commit `infra/terraform/.terraform.lock.hcl`.** It is what pins the provider version across
> cohorts, and it is part of the harness, not a Terraform detail.

## 3. The devcontainer

`.devcontainer/devcontainer.json` — every version pinned, because an unpinned tool grades two
cohorts differently:

```json
{
  "name": "iac-hiring-test",
  "image": "mcr.microsoft.com/devcontainers/base:ubuntu-22.04",
  "features": {
    "ghcr.io/devcontainers/features/azure-cli:1": { "version": "2.64.0", "installBicep": true },
    "ghcr.io/devcontainers/features/terraform:1": {
      "version": "1.9.5", "tflint": "0.53.0", "terragrunt": "none"
    },
    "ghcr.io/devcontainers/features/powershell:1": { "version": "7.4.5" },
    "ghcr.io/devcontainers/features/python:1": { "version": "3.11" },
    "ghcr.io/devcontainers/features/github-cli:1": {}
  },
  "postCreateCommand": "bash .devcontainer/post-create.sh",
  "remoteUser": "vscode",
  "customizations": {
    "vscode": {
      "extensions": [
        "ms-azuretools.vscode-bicep",
        "hashicorp.terraform",
        "msazurermtools.azurerm-vscode-tools",
        "ms-vscode.powershell",
        "redhat.vscode-yaml",
        "editorconfig.editorconfig",
        "github.vscode-github-actions"
      ],
      "settings": {
        "[bicep]": { "editor.formatOnSave": true },
        "[terraform]": {
          "editor.formatOnSave": true,
          "editor.defaultFormatter": "hashicorp.terraform"
        },
        "files.eol": "\n"
      }
    }
  },
  "containerEnv": { "AZURE_CORE_OUTPUT": "json" }
}
```

`.devcontainer/post-create.sh` — a verifier that actually fails, and that installs every tool the
README promises:

```bash
#!/usr/bin/env bash
set -euo pipefail

echo "==> Installing supplementary tools"
az bicep install --only-show-errors || az bicep upgrade --only-show-errors
pip install --quiet --no-input "checkov==3.2.257"          # (FIX 6) README promises it; install it
pwsh -NoProfile -Command \
  "if (-not (Get-Module -ListAvailable -Name arm-ttk)) {
     Install-Module -Name arm-ttk -RequiredVersion 0.11.1 -Scope CurrentUser -Force -AcceptLicense
   }"

echo "==> Verifying toolchain"
missing=0
for tool in az terraform tflint pwsh checkov; do
  if command -v "$tool" >/dev/null 2>&1; then
    printf '  ok      %s\n' "$tool"
  else
    printf '  MISSING %s\n' "$tool"; missing=1
  fi
done
az bicep version >/dev/null 2>&1 || { echo "  MISSING bicep"; missing=1; }

# (FIX 5) No `|| true` anywhere above: a broken container must fail here, not on
# the candidate's first script run.
[ "$missing" -eq 0 ] || { echo "Toolchain incomplete — see above."; exit 1; }
echo "==> Ready. Run: ./scripts/<bicep|terraform>.sh"
```

## 4. The scripts

One per technology. Linear, no argument parsing, no prompts, deploy commented out. The opening line
is not optional — it is the behaviour the README describes.

`scripts/bicep.sh`:

```bash
#!/usr/bin/env bash
set -euo pipefail          # (FIX 1) the README promises this; without it validate failures continue

LOCATION="${AZURE_LOCATION:-westeurope}"
TEMPLATE="infra/bicep/main.bicep"
PARAMETERS="infra/bicep/main.bicepparam"

echo "### 1/3 validate (offline)"
az bicep build --file "${TEMPLATE}" --stdout > /dev/null
az bicep lint  --file "${TEMPLATE}"

# ---------------------------------------------------------------------------
# The steps below need an Azure subscription. Uncomment when ready.
# ---------------------------------------------------------------------------
# echo "### 2/3 plan (what-if at subscription scope)"
# az deployment sub what-if \
#   --location "${LOCATION}" --template-file "${TEMPLATE}" --parameters "${PARAMETERS}"
#
# echo "### 3/3 deploy (resource group is created by the template)"
# az deployment sub create \
#   --location "${LOCATION}" --template-file "${TEMPLATE}" --parameters "${PARAMETERS}"
```

`scripts/terraform.sh`:

```bash
#!/usr/bin/env bash
set -euo pipefail

LOCATION="${AZURE_LOCATION:-westeurope}"
NAME_PREFIX="${NAME_PREFIX:-iactest}"
TF_DIR="infra/terraform"

echo "### 1/3 validate (offline)"
terraform -chdir="${TF_DIR}" fmt -recursive -check
terraform -chdir="${TF_DIR}" init -backend=false -input=false
terraform -chdir="${TF_DIR}" validate
tflint --chdir="${TF_DIR}" --recursive

# ---------------------------------------------------------------------------
# The steps below need an Azure subscription. Uncomment when ready.
# ---------------------------------------------------------------------------
# echo "### 2/3 plan"
# terraform -chdir="${TF_DIR}" init -input=false
# terraform -chdir="${TF_DIR}" plan \
#   -var "name_prefix=${NAME_PREFIX}" -var "location=${LOCATION}" -out tfplan.bin
#
# echo "### 3/3 deploy"
# terraform -chdir="${TF_DIR}" apply -auto-approve tfplan.bin
```

Make them executable: `chmod +x scripts/*.sh`.

## 5. The composition roots

### 5a. Bicep

`infra/bicep/main.bicep` — subscription scope so the template creates its own resource group, which
removes the "run `az group create` first" prerequisite entirely:

```bicep
// =============================================================================
// Central Bicep composition (subscription-scope).
// Creates the resource group and dispatches all modules into it.
// Each module reference below points at a folder YOU MUST CREATE:
//   ./modules/<name>/main.bicep
// =============================================================================

targetScope = 'subscription'

@description('Azure region for all resources')
param location string = deployment().location

@description('Lower-case short prefix used to name resources (e.g. "iactest")')
@minLength(3)
@maxLength(10)
param namePrefix string

@description('Resource group name (defaults to rg-<namePrefix>)')
param resourceGroupName string = 'rg-${namePrefix}'

@description('Common tags applied to all resources')
param tags object = {
  workload: 'iac-hiring-test'
  managedBy: 'bicep'
}

resource rg 'Microsoft.Resources/resourceGroups@2022-09-01' = {
  name: resourceGroupName
  location: location
  tags: tags
}

module network './modules/network/main.bicep' = {
  name: 'network'
  scope: rg
  params: { location: location, namePrefix: namePrefix, tags: tags }
}

module privateDns './modules/private-dns/main.bicep' = {
  name: 'private-dns'
  scope: rg
  params: { namePrefix: namePrefix, vnetId: network.outputs.vnetId, tags: tags }
}

module keyvault './modules/keyvault/main.bicep' = {
  name: 'keyvault'
  scope: rg
  params: {
    location: location
    namePrefix: namePrefix
    peSubnetId: network.outputs.peSubnetId
    privateDnsZoneId: privateDns.outputs.keyVaultZoneId
    tags: tags
  }
}

module cosmos './modules/cosmosdb/main.bicep' = {
  name: 'cosmosdb'
  scope: rg
  params: {
    location: location
    namePrefix: namePrefix
    peSubnetId: network.outputs.peSubnetId
    privateDnsZoneId: privateDns.outputs.cosmosZoneId
    tags: tags
  }
}

module webapp './modules/webapp/main.bicep' = {
  name: 'webapp'
  scope: rg
  params: {
    location: location
    namePrefix: namePrefix
    webSubnetId: network.outputs.webSubnetId
    keyVaultName: keyvault.outputs.name
    cosmosAccountName: cosmos.outputs.accountName
    tags: tags
  }
}

output resourceGroupName string = rg.name
output webAppHostname string = webapp.outputs.defaultHostname
output keyVaultName string = keyvault.outputs.name
output cosmosAccountName string = cosmos.outputs.accountName
```

`infra/bicep/main.bicepparam`:

```bicep
using './main.bicep'

param namePrefix = 'iactest'
// param location = 'westeurope'   // override if needed
```

`infra/bicep/bicepconfig.json` — promote the rule that backs the "no secrets in source" requirement
to build-blocking, so the linter is part of the contract rather than advice:

```json
{
  "analyzers": {
    "core": {
      "enabled": true,
      "rules": {
        "no-hardcoded-env-urls":    { "level": "warning" },
        "secure-parameter-default": { "level": "error" }
      }
    }
  }
}
```

### 5b. Terraform

`versions.tf`:

```hcl
terraform {
  required_version = ">= 1.6.0"
  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 4.0"
    }
  }
}

provider "azurerm" {
  features {}
}
```

`variables.tf`:

```hcl
variable "location" {
  type        = string
  default     = "westeurope"
  description = "Azure region"
}

variable "name_prefix" {
  type        = string
  default     = "iactest"
  description = "Lower-case short prefix used to name resources"

  validation {
    condition     = can(regex("^[a-z0-9]{3,10}$", var.name_prefix))
    error_message = "name_prefix must be 3-10 lowercase alphanumeric chars."
  }
}

variable "tags" {
  type = map(string)
  default = {
    workload  = "iac-hiring-test"
    managedBy = "terraform"
  }
}
```

`main.tf` — the root owns the resource group, mirroring the Bicep track:

```hcl
# =============================================================================
# Central Terraform composition.
# Each module block below points at a folder YOU MUST CREATE:
#   ./modules/<name>/  (main.tf, variables.tf, outputs.tf)
# =============================================================================

resource "azurerm_resource_group" "this" {
  name     = "rg-${var.name_prefix}"
  location = var.location
  tags     = var.tags
}

module "network" {
  source              = "./modules/network"
  location            = azurerm_resource_group.this.location
  resource_group_name = azurerm_resource_group.this.name
  name_prefix         = var.name_prefix
  tags                = var.tags
}

module "private_dns" {
  source              = "./modules/private-dns"
  resource_group_name = azurerm_resource_group.this.name
  vnet_id             = module.network.vnet_id
  tags                = var.tags
}

module "keyvault" {
  source              = "./modules/keyvault"
  location            = azurerm_resource_group.this.location
  resource_group_name = azurerm_resource_group.this.name
  name_prefix         = var.name_prefix
  pe_subnet_id        = module.network.pe_subnet_id
  private_dns_zone_id = module.private_dns.keyvault_zone_id
  tags                = var.tags
}

module "cosmosdb" {
  source              = "./modules/cosmosdb"
  location            = azurerm_resource_group.this.location
  resource_group_name = azurerm_resource_group.this.name
  name_prefix         = var.name_prefix
  pe_subnet_id        = module.network.pe_subnet_id
  private_dns_zone_id = module.private_dns.cosmos_zone_id
  tags                = var.tags
}

module "webapp" {
  source              = "./modules/webapp"
  location            = azurerm_resource_group.this.location
  resource_group_name = azurerm_resource_group.this.name
  name_prefix         = var.name_prefix
  web_subnet_id       = module.network.web_subnet_id
  key_vault_id        = module.keyvault.id
  cosmos_account_id   = module.cosmosdb.id
  tags                = var.tags
}
```

`outputs.tf`:

```hcl
output "web_app_hostname" {
  description = "Default hostname of the deployed web app"
  value       = module.webapp.default_hostname
}

output "key_vault_id" {
  description = "Key Vault resource ID"
  value       = module.keyvault.id
}

output "cosmos_account_id" {
  description = "Cosmos DB account resource ID"
  value       = module.cosmosdb.id
}
```

### 5c. The ARM track (optional)

**Default recommendation: omit it.** Bicep and Terraform cover the market, ARM authoring is a
diminishing skill, and the track carries a structural problem the other two do not. If you want to
assess ARM *reading* ability, a review question does it better than four hours of authoring.

If you include it, resolve the problem the source scaffold shipped with. Linked templates are
fetched **by ARM over HTTPS** — ARM cannot read a module file from the machine running the CLI.
`[docs]` So a root that dispatches `templateLink` modules cannot deploy from `--template-file`,
which is exactly how the script invokes it. Exactly one of these three has to be true, and the
brief has to say which:

| Configuration | Modules stay separate files? | Candidate prerequisite |
|---|---|---|
| **Inline nested templates** (`properties.template`) | No — one large JSON root | None. Works from `--template-file`, but loses the modularity the exercise grades |
| **Linked templates + published artifacts** | Yes | Must publish `modules/` to an HTTPS location and pass its base URL |
| **Template specs**, one per module | Yes | Must `az ts create` each module before any deploy works |

The second is the most faithful to real ARM practice and keeps the scaffold's shape. Three changes
make it work:

- **`_artifactsLocation` is a required parameter with no default.** The original defaulted it to
  `[deployment().properties.templateLink.uri]`, which is unset under `--template-file` — so the
  default was unevaluable in the only way the script runs.
- **Add a publish step to `scripts/arm.sh`**, commented alongside deploy, that uploads
  `infra/arm/modules/` and passes the resulting base URL plus a SAS token.
- **Say in the brief that ARM's offline check is ARM-TTK on the module files.** `validate` and
  `what-if` only check the **outer** template, so they pass while all five modules are broken.

Otherwise the root mirrors the Bicep one: subscription-scope schema, a
`Microsoft.Resources/resourceGroups` resource, then one inner-scoped nested deployment per module in
the order from section 1, reading cross-module values with
`[reference('<module>').outputs.<name>.value]`.

## 6. CI

`.github/workflows/lint.yml`. Three of the seven defects lived in this file, so read the comments:

```yaml
name: lint

on:
  push:
    branches: [main]
  pull_request:

permissions:
  contents: read

jobs:
  bicep:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Install Bicep
        run: az bicep install && az bicep version
      - name: Build every Bicep file
        run: |
          set -euo pipefail
          found=0
          while IFS= read -r f; do
            echo "==> $f"; found=$((found + 1))
            az bicep build --file "$f" --stdout > /dev/null
          done < <(find infra -name '*.bicep')
          echo "Bicep files built: $found"        # a check that silently matched nothing reads as a pass

  terraform:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: hashicorp/setup-terraform@v3
        with:
          terraform_version: 1.9.5
      - uses: terraform-linters/setup-tflint@v4
        with:
          tflint_version: v0.53.0                 # (FIX 4) was `latest` — pin it
      - name: terraform fmt
        run: terraform fmt -recursive -check infra
      - name: validate + tflint, per directory containing .tf
        run: |
          set -euo pipefail
          found=0
          # (FIX 2) discover by CONTENT. `find infra -type d -name terraform` matched
          # only the root and never validated a single candidate module.
          while IFS= read -r d; do
            echo "==> $d"; found=$((found + 1))
            (cd "$d" && terraform init -backend=false -input=false -no-color \
                     && terraform validate -no-color && tflint --no-color)
          done < <(find infra -type f -name '*.tf' -exec dirname {} \; | sort -u)
          echo "Terraform directories checked: $found"

  security:
    runs-on: ubuntu-latest
    # (FIX 3) ONE mute, not two. `continue-on-error` here plus `soft_fail` on the
    # action meant nothing about security could ever fail, while the rubric claimed
    # findings were addressed. Advisory is fine; say so in the README and keep the log.
    steps:
      - uses: actions/checkout@v4
      - name: Checkov
        uses: bridgecrewio/checkov-action@v12.2875.0   # (FIX 4) was @master
        with:
          directory: infra
          quiet: true
          soft_fail: true
```

Add an `arm` job running ARM-TTK only if you kept that track.

## 7. The candidate-facing README

Write the brief in this order: architecture paragraph, ASCII diagram, requirements, non-functional
requirements, repository layout, getting started, the scripts, the rubric, submission instructions,
reference links. Four sentences carry most of the weight, and all four are easy to get wrong:

- **The time-box and the priority.** *"You are expected to spend 2–4 hours. Quality > completeness —
  a small, clean, secure, idiomatic solution beats a sprawling one. Commit early, commit often; we
  read your git history."*
- **What the empty folders mean.** *"The composition files already wire together five modules. The
  `infra/<tech>/modules/<name>/` folders exist but are empty; populating them in your chosen
  technology is the core of the exercise. Delete the trees for the technologies you don't use."*
- **That CI is red until you finish.** *"The roots reference modules that do not exist yet, so the
  Bicep job fails until all five are implemented. Use the scripts as your feedback loop; CI is a
  final check, not a progress indicator."* (FIX 1 — the original implied candidates should keep CI
  green, which is unreachable by design. See the green-baseline trade-off in
  [exercise-design.md](./exercise-design.md).)
- **Which checks gate and which inform.** *"Checkov runs advisory — read its output and justify
  anything you leave."*

Describe the scripts as what they do, not what you intended: three steps, `set -euo pipefail`,
deploy commented out, defaults overridable via `AZURE_LOCATION` and `NAME_PREFIX`. If you later
change a script, change this paragraph in the same commit.

`infra/README.md` is shorter: the tree, the module responsibility table from section 1, the target
architecture diagram, and the deliverables. It exists so a candidate who starts in `infra/` still
finds the contract.

## 8. Verify the harness before anyone uses it

The scaffold is not finished when the files exist. It is finished when a **deliberately broken
submission fails every check you expect**, for the expected reason.

One subtlety first, because it invalidates the obvious test: the Bicep CI job is **already red** on
a fresh scaffold, because the root references five modules that do not exist. So you cannot use the
root build to prove anything else works. Test the analyzer on a standalone file instead:

```bash
# Does bicepconfig.json actually block a secret in source?
cat > /tmp/probe.bicep <<'EOF'
@secure()
param apiKey string = 'hunter2'
output k string = apiKey
EOF
cp infra/bicep/bicepconfig.json /tmp/
az bicep build --file /tmp/probe.bicep --stdout >/dev/null   # MUST fail: secure-parameter-default
```

Then push a branch with the remaining three faults and read the CI output:

```bash
git switch -c harness-selftest

# 1. an invalid module, to prove CI reaches modules at all
mkdir -p infra/terraform/modules/network
printf 'resource "azurerm_virtual_network" "x" {
  name = 
}
'   > infra/terraform/modules/network/main.tf

# 2. an unformatted file
printf 'variable   "y"  {
 type=string
}
' >> infra/terraform/modules/network/main.tf

# 3. a plan artifact, to prove .gitignore covers it
touch infra/terraform/tfplan.bin
git status --porcelain | grep -q tfplan && echo "FAIL: tfplan.bin is not ignored"

git push -u origin harness-selftest
```

| Expectation | Confirms |
|---|---|
| Terraform job fails **and its count line reads > 1** | Discovery reaches modules, not just the root |
| `terraform fmt` fails | Formatting is enforced recursively |
| `/tmp/probe.bicep` build fails | `bicepconfig.json` is build-blocking, not advisory |
| `git status` does **not** list `tfplan.bin` | `.gitignore` covers what the harness writes |

The count line is the one that matters most. A discovery expression that matches nothing still exits
zero, so a job can pass while checking no files at all — printing the count is what makes that
visible.

Finally, confirm the scripts stop at the first error:

```bash
grep -L 'set -euo pipefail' scripts/*.sh   # must print nothing
./scripts/terraform.sh; echo "exit=$?"     # must be non-zero while a module is broken
```

**Anything that stays green is a check you do not have.** Delete the branch when done.

## Divergences from the source scaffold

Nine changes, all harness repairs. Nothing about the *exercise* changed — same brief, same five
modules, same interface, same rubric, same time-box. Defect numbers refer to
[harness-and-fairness.md](./harness-and-fairness.md), which explains each one and its class.

| Change | Fixes |
|---|---|
| `set -euo pipefail` in all scripts; README text corrected to match | Defect 1 |
| CI Terraform discovery by `.tf` content, plus a printed file count | Defect 2 |
| `continue-on-error` dropped from the security job, `soft_fail` kept | Defect 3 |
| `tflint` and `checkov-action` pinned to versions | Defect 4 |
| `post-create.sh` verifies and exits non-zero; no `\|\| true` | Defect 5 |
| Checkov installed in the devcontainer | Defect 6 |
| `*tfplan*` active in `.gitignore` rather than commented | Defect 7 |
| ARM track optional; `_artifactsLocation` required; publish step documented | The ARM asymmetry |
| `az` and Python pinned in the devcontainer | Same class as defect 4 |

Two additions that are not repairs: the README now states that **CI is red until all five modules
exist** (so candidates use the scripts as their loop), and section 8 above exists at all.

## Related

- [exercise-design.md](./exercise-design.md) — why the scaffold is shaped this way, the designs it
  replaced, and the rubric.
- [harness-and-fairness.md](./harness-and-fairness.md) — the seven defects in full, each with the
  class of mistake it belongs to.
- [azure-private-app-pattern.md](./azure-private-app-pattern.md) — the architecture, component
  choice, and the ARM asymmetry.
- [develop-infrastructure](../../develop-infrastructure/SKILL.md) — what a correct module looks
  like, for writing the reference solution you grade against.
