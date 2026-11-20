# The architecture under test, and the per-technology asymmetries

> **Source.** `[repo]` — the shipped scaffold and the design discussion behind its component
> choices. `[docs]` marks vendor-documented Azure behaviour; `[deduced]` an inference; `[?]` a claim
> worth verifying before you rely on it.
>
> **This file does not explain private link.** The three-part endpoint + zone + zone-group
> mechanism, `groupId` values, NSG rules and Bicep idiom are all in
> [develop-infrastructure](../../develop-infrastructure/references/bicep-azure-resources.md) — read
> that to grade the architecture. What follows is only what is specific to *choosing* these
> components for an exercise and running three technology tracks over them.

## The shape

```
                     ┌──────────────────────────────┐
                     │  Virtual Network 10.0.0.0/16 │
 Internet ──HTTPS──► │ ┌──────────────────────────┐ │
                     │ │ snet-web (delegated to   │◄┼── Web App (VNet integrated)
                     │ │  Microsoft.Web/serverFarms)│ │
                     │ └──────────────────────────┘ │
                     │ ┌──────────────────────────┐ │
                     │ │ snet-pe (PE network      │◄┼── PE → Cosmos DB
                     │ │  policies disabled)      │◄┼── PE → Key Vault
                     │ └──────────────────────────┘ │
                     │ ┌──────────────────────────┐ │
                     │ │ snet-future (reserved)   │ │
                     │ └──────────────────────────┘ │
                     └──────────────────────────────┘
```

The specific properties a grader looks for, beyond the generic private-link checklist:

- `snet-web` **delegated** to `Microsoft.Web/serverFarms`, and the Web App with
  `vnetRouteAllEnabled = true` — without the latter, only RFC1918 traffic goes through the VNet and
  the private endpoints are bypassed for anything that resolves publicly. A candidate who sets up
  perfect private endpoints and omits this has a working-looking app that is not actually private.
- `snet-pe` with **private endpoint network policies disabled**, which is a subnet property, not a
  property of the endpoint.
- Private DNS zones `privatelink.vaultcore.azure.net` and `privatelink.documents.azure.com`, both
  **linked to the VNet**, with a zone group on each endpoint. The classic failure — endpoint exists,
  hostname still resolves to the public IP — is the missing zone group, and it is worth grading
  explicitly because it is the single most common mistake.
- Key Vault with `publicNetworkAccess = Disabled`, **RBAC authorisation mode** (not access
  policies), soft delete and purge protection on.
- The Web App's **system-assigned** managed identity granted `Key Vault Secrets User`, and the
  Cosmos connection string consumed through a **Key Vault reference** App Setting rather than stored
  as a plain setting:

  ```
  COSMOS_CONNECTION_STRING = @Microsoft.KeyVault(SecretUri=https://<kv>.vault.azure.net/secrets/cosmos-conn/)
  ```

  App Service resolves that at startup using the identity, so no secret reaches code, config files
  or the deployment. A candidate who puts the connection string in an App Setting has met the
  functional requirement and failed the security one — which is exactly the distinction the module
  exists to surface. `[docs]`

## Why Key Vault is the *easier* teaching resource, not the harder one

The tempting simplification is to swap Key Vault for a storage account — "blob is more familiar".
It makes the exercise harder and narrower at the same time, and the reasoning is worth keeping
because it generalises to any component choice.

**Key Vault is the simplest private-endpoint service Azure has.** One `groupId` (`vault`), one DNS
zone, and the App Service integration is a built-in platform feature: one App Setting line plus one
RBAC role assignment.

**A storage account is materially harder:**

- It has **multiple sub-resources** — `blob`, `file`, `queue`, `table`, `dfs`, `web` — and **each
  needs its own private endpoint and its own private DNS zone**
  (`privatelink.blob.core.windows.net`, `privatelink.file.core.windows.net`, …). Candidates create
  one and silently break the others,
  which produces a submission that looks right and fails in a way neither of you will diagnose in a
  review slot. `[docs]`
- Public access has **two independent layers**: `publicNetworkAccess` on the account, and
  `allowBlobPublicAccess` for anonymous container access. Disabling one and not the other is an easy
  and invisible miss.
- Wiring a Web App to read blobs privately needs either a SAS token — and then where does *that*
  live, which puts you back at Key Vault — or RBAC plus managed identity plus SDK code, which is
  app-side plumbing the exercise is not trying to test.
- Networking-wise it adds nothing over Cosmos DB. Both are "a data service behind a private
  endpoint", so you would be testing the same skill twice and losing a different one.

**And removing Key Vault removes the most discriminating signal in the test.** Managed identity +
RBAC + Key Vault references is the combination that separates a candidate who has shipped a private
workload from one who has followed a networking tutorial.

If the exercise genuinely needs to be shorter, the better cuts are:

1. **Drop Cosmos DB, keep Key Vault.** VNet + private DNS + Key Vault + Web App is the *minimum*
   private-app pattern and still exercises four of the five skills.
2. **Keep all five, make the Cosmos private endpoint a bonus.** Require private-only on Key Vault;
   let candidates who finish early demonstrate it on Cosmos.

If you do swap, swap **Cosmos → storage (blob only)** and keep Key Vault — cheaper, faster to
deploy, free-tier available — and accept the multi-sub-resource trap as part of the test rather than
by accident.

## Cosmos DB quirks worth knowing before you grade

Cosmos is the finickiest component in the stack, and most of the friction is Azure rather than the
candidate. Do not read these as skill signals:

- **Deletion lag.** A deleted account's name is not immediately reusable, so a candidate who tears
  down and redeploys with the same `namePrefix` can hit a name conflict that is nothing to do with
  their code.
- **Free-tier conflicts.** Only one free-tier Cosmos account is permitted per subscription, so in a
  shared sandbox the second candidate to try it fails. Either pre-decide the SKU in the brief or
  make sure each candidate has their own subscription.
- **Geo-replication settings** interact with private endpoints and with what-if output in ways that
  produce confusing diffs on re-runs.

These are also why the "idempotent — re-running the deploy produces no changes" requirement is worth
checking by actually re-running rather than by reading the code: Cosmos is where a non-idempotent
diff usually shows up. `[repo]`

## The three tracks are not at parity

The scaffold offers Bicep, Terraform and ARM. Two of them work locally with the scripts as shipped.
The third does not, and it is the one least likely to be chosen by a strong candidate — so the trap
disproportionately catches someone already struggling.

### Bicep and Terraform

Both work offline and end-to-end. Bicep's root is `targetScope = 'subscription'` and creates the
resource group; Terraform's root has `azurerm_resource_group`. `az bicep build` and
`terraform validate` both run with no Azure credentials, and `what-if`/`plan` work once the
candidate authenticates.

One Bicep detail worth noting: `bicepconfig.json` promotes analyzer rules to build-blocking.

```json
{ "analyzers": { "core": { "enabled": true, "rules": {
  "no-hardcoded-env-urls":    { "level": "warning" },
  "secure-parameter-default": { "level": "error" }
} } } }
```

`secure-parameter-default` at `error` means a `@secure()` parameter with a default **fails the
build**, not just lints — which is the right setting for a test whose brief says "no secrets in
source", and worth pointing at in the brief so candidates know the linter is part of the contract.

### ARM: linked templates cannot resolve from a local file

The ARM root dispatches each module as a linked template:

```json
"templateLink": {
  "uri": "[uri(parameters('_artifactsLocation'), concat('modules/network/azuredeploy.json', parameters('_artifactsLocationSasToken')))]"
}
```

with

```json
"_artifactsLocation": { "type": "string", "defaultValue": "[deployment().properties.templateLink.uri]" }
```

Two documented behaviours collide here:

1. **`deployment().properties.templateLink.uri` only exists when the deployment was started from a
   URI.** Deploying with `--template-file` — which is precisely what `scripts/arm.sh` does — leaves
   `templateLink` unset, so the default cannot evaluate. `[docs]`
2. **Linked templates must be reachable over HTTPS at deploy time.** ARM fetches them itself; it
   cannot read a file from the machine running the CLI. `[docs]`

So the ARM track as shipped cannot deploy with its own script. The template's metadata is honest
about it — *"use template specs OR replace these with inline nested templates if running
locally"* — but that note lives in the JSON, not in the candidate-facing README, so it is found by
whoever reads the template most carefully rather than by everyone.

If you keep the ARM track, pick one and say so in the brief:

- **Inline nested templates** (`properties.template` instead of `properties.templateLink`) — works
  from a local file, at the cost of one large JSON file, which weakens the modularity the exercise
  is trying to grade.
- **Template specs**, published once per module, with `_artifactsLocation` pointed at them — keeps
  modularity, but adds a publish step the candidate has to perform before any deploy works.
- **Drop the ARM track.** Honest, and ARM is a diminishing skill; Bicep and Terraform cover the
  market. If the goal is to see whether a candidate can read ARM, a review question does that
  better than four hours of authoring it.

### The ARM validation ladder

Since the deploy path is blocked, know what each offline and online check actually buys — this is
also useful for grading a Bicep submission:

| Check | Needs Azure? | Catches |
|---|---|---|
| `python3 -m json.tool` | no | JSON syntax only — the weakest possible check |
| `az bicep decompile --file template.json` | no | Schema and type issues, by round-tripping ARM→Bicep. Lightweight and free; this is what `arm.sh` actually runs, despite the README calling it a "JSON syntax check" |
| ARM-TTK (`Test-AzTemplate`) | no | Best-practice linting: hardcoded locations, secure-string defaults, parameter naming, output references |
| `az deployment sub validate` | yes (login) | Server-side ARM validation — schema, required properties, resource types, API versions, expression errors. Creates nothing |
| `az deployment sub what-if` | yes (login) | Everything `validate` does **plus** a change preview |

Two consequences. **A separate `validate` step is redundant when you already run `what-if`** — if
what-if passes, the template is structurally sound. And more importantly: **`validate` and `what-if`
only check the outer template.** Linked templates are not fetched unless they are publicly
reachable, so on the ARM track a green what-if says nothing at all about the five module templates
that are the candidate's actual work. `[docs]`

That last point is the deepest reason the ARM track needs different treatment: its modules are
structurally unverifiable by the harness, which means ARM-TTK on the module files is the only check
you have.

## Related

- [develop-infrastructure](../../develop-infrastructure/SKILL.md) — private endpoints and DNS zones
  in full, the NSG rule set, Bicep at subscription scope, and `bicepconfig.json` as part of the
  build. The reference for grading the architecture.
- [exercise-design.md](./exercise-design.md) — why these five components, and what you lose by
  substituting one.
- [harness-and-fairness.md](./harness-and-fairness.md) — the scripts that run these checks, and
  where they do not fire.
