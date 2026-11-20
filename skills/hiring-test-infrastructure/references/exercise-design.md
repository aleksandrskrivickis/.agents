# Designing the exercise and its scaffold

> **Source.** `[repo]` — from an Azure IaC hiring test and the design sessions that produced it,
> including the designs that were explicitly rejected. `[docs]` marks a vendor-documented
> constraint; `[deduced]` an inference.

## The brief: what makes it gradeable

The exercise is one paragraph of architecture plus a requirements list. The architecture in the
source test:

> A Linux App Service with **private connectivity** to Cosmos DB and Key Vault. The app reads its
> configuration from Key Vault using a managed identity. All data traffic stays inside a VNet with
> proper segmentation, and the network must accommodate **future components** (queues, caches,
> more apps) without rework.

Three properties make that gradeable rather than merely plausible:

- **Every requirement is observable.** `publicNetworkAccess = Disabled`, a managed identity, a
  delegated subnet, a Key Vault reference in an App Setting — each is a thing you can look for in
  the diff or the deployed resource. "Follows best practice" is not.
- **One requirement tests judgement rather than recall.** `snet-future` exists only to see whether
  the candidate reserves address space sensibly and parameterises the module so a sixth component
  can be added. There is no single right answer, which is the point.
- **The non-functional list is short and absolute.** Consistent tags, idempotent re-runs, no secrets
  in source, no public IPs except the App Service default endpoint. Four lines, all binary.

Say the time-box and the priority explicitly — *2–4 hours, quality over completeness, a small clean
secure solution beats a sprawling one* — because candidates optimise for what you state. Without
it, the conscientious ones over-build and the pragmatic ones look lazy, which inverts the signal.

## The scaffold: a wired root over empty modules

The decision that makes the whole thing work:

```bicep
targetScope = 'subscription'

resource rg 'Microsoft.Resources/resourceGroups@2022-09-01' = {
  name: resourceGroupName
  location: location
  tags: tags
}

module network './modules/network/main.bicep' = {    // <- this folder is empty
  name: 'network'
  scope: rg
  params: { location: location, namePrefix: namePrefix, tags: tags }
}

module privateDns './modules/private-dns/main.bicep' = {
  name: 'private-dns'
  scope: rg
  params: { namePrefix: namePrefix, vnetId: network.outputs.vnetId, tags: tags }
}
// … keyvault, cosmosdb, webapp
```

Read what that root has already decided on the candidate's behalf: the module **names**, each
module's **inputs**, the **outputs** it must expose (`network.outputs.vnetId`,
`network.outputs.peSubnetId`, `privateDns.outputs.keyVaultZoneId`), and the **dependency order**
implied by those references. The candidate implements five contracts. You grade five
implementations against the same interface, and reviewing the tenth submission is as fast as the
first.

Keep the empty folders in Git with a `.gitkeep` so the structure is visible on clone rather than
something the candidate has to infer from the root file.

### Two designs this replaced

Worth knowing, because both are the obvious first instinct:

1. **Module stubs per technology** — `infra/modules/network/{bicep,terraform,arm}/` with a
   skeleton file in each. Rejected: it triples the surface, and a stub with parameters already
   declared invites filling in blanks rather than designing a module. Pre-written stubs also need
   their own linter suppressions (`no-unused-params` fires on every parameter a stub declares but
   does not use), so you end up weakening the linter for code nobody will ship.
2. **Flat multi-technology stubs** — one folder per component containing a Bicep, a Terraform and an
   ARM file side by side, candidate deletes the rest. Rejected as still duplicative, and it forces
   the candidate to work out which files are theirs before writing any code.

The third attempt — *"each language should simply have a centralised module that refers to
non-existent modules that the candidate needs to create"* — is the one above. The progression is
worth recording because the final design looks under-built until you see what it replaces: its
whole strength is the **absence** of stubs.

## One module, one skill

Five modules, five different competencies, no overlaps:

| Module | Skill it exercises |
|---|---|
| `network` | VNet design, subnet sizing, delegation, NSG rules |
| `private-dns` | Zone management and VNet links |
| `cosmosdb` | A private endpoint to a **data-plane** service |
| `keyvault` | A private endpoint to a **secrets/identity** service, plus managed identity, RBAC and App Service Key Vault references |
| `webapp` | VNet integration, managed identity, consuming a secret without storing it |

Use the table as a design test, not decoration. If two rows name the same skill, one of them is
costing the candidate time and telling you nothing — the earlier version of this test had nine
modules (resource group, VNet, NSG, storage, Key Vault, Log Analytics, managed identity, role
assignment, private endpoint) which collapse to about four skills. Cutting to five that each buy
something distinct is what made a 2–4 hour box realistic.

The same table tells you what you lose when you change a component. Swapping Key Vault for a
storage account removes the **managed identity + RBAC + Key Vault reference** row entirely — which
is the row that distinguishes someone who has shipped a private workload from someone who followed
a tutorial. See
[azure-private-app-pattern.md](./azure-private-app-pattern.md) for why it also does not make the
exercise easier.

## Gate the deploy, do not remove it

Each per-technology script runs `validate → plan → deploy`, with the deploy block **commented out**:

```bash
echo "### 1/3 validate (offline)"
az bicep build --file "${TEMPLATE}" --stdout > /dev/null
az bicep lint  --file "${TEMPLATE}"

# ---------------------------------------------------------------------------
# The steps below need an Azure subscription. Uncomment when ready.
# ---------------------------------------------------------------------------
# echo "### 2/3 plan (what-if at subscription scope)"
# az deployment sub what-if --location "${LOCATION}" --template-file "${TEMPLATE}" …
```

A comment beats a `--dry-run` default on three counts: the candidate can iterate offline with no
Azure account at all, nobody deploys into your subscription by accident, and the commented commands
**document the real invocation** — including the flags — in a way a flag-parsed script does not.
Keep the offline step genuinely offline so the loop stays fast.

### Let the IaC create its own resource group

This one took a detour worth short-cutting. The scripts originally ran `az group create` before
planning. Moving that into the commented deploy block broke the plan step, because
`az deployment group what-if` needs the group to exist — so the choice looked like "pre-create a
group outside the IaC" or "no working plan step".

The resolution is to make resource-group creation part of the code under test:

- **Bicep / ARM** — `targetScope = 'subscription'` (and the subscription deployment schema for ARM),
  with a `Microsoft.Resources/resourceGroups` resource and every module scoped into it.
- **Terraform** — `azurerm_resource_group` in the root, which it already had.

Scripts then use `az deployment sub what-if|create --location …` with no `--resource-group` and no
pre-step. The prerequisite disappears, and as a bonus "the resource group is created by the IaC
itself" becomes a requirement you can grade. `[repo]`

## The rubric

Weight it, publish it, and make every row point at something in the diff:

| Area | What it buys you |
|---|---|
| Correctness | Modules deploy cleanly; private endpoints actually resolve to private IPs |
| Security | No public exposure of data services; least-privilege NSGs and RBAC; managed identity |
| Code quality | Idiomatic for the chosen technology; sensible parameterisation; no magic strings |
| Modularity | Reusable modules with explicit inputs and outputs; the root stays thin |
| Future-proofing | `snet-future` properly reserved; modules accept extension without breaking |
| Testing and CI | The scripts pass; CI is green; linter findings addressed or justified |
| Git hygiene | Atomic commits, meaningful messages, no committed secrets or state files |

Two rows carry a debt the author has to pay first. **"CI is green"** is only meaningful if the
harness actually checks the candidate's code, and **"no committed state files"** is only fair if
`.gitignore` covers everything the harness writes. Both were violated in the shipped scaffold —
[harness-and-fairness.md](./harness-and-fairness.md).

Ask for a short PR description: technology chosen and why, trade-offs made, what they would do with
another day, and any subscription preconditions. The trade-offs paragraph is often the
highest-signal part of the whole submission, because it shows what they noticed and chose not to
do — which is the actual job.

### Bonus items, kept explicitly optional

Diagnostic settings to Log Analytics, module versioning (a Bicep registry or pinned Terraform
modules), integration tests (`pester`, `terratest`, `az deployment group validate`), and
cost-aware SKU choices documented in the PR. State clearly that they are not required, or
conscientious candidates will spend the time-box on them.

## The green-baseline trade-off, stated honestly

Conventional advice is that a scaffold should **pass its own CI before the candidate writes
anything**, so a candidate can always tell their errors from yours. This design knowingly breaks
that: the roots reference modules that do not exist, so `az bicep build` fails five times from the
first commit and the Bicep CI job is red until the last module lands.

That is the cost of making the compile error the brief, and it is defensible — but it has a
consequence the README must carry and the source one did not:

> **With this scaffold, CI cannot be the signal.** "Green CI" is only reachable at the very end, so
> a candidate halfway through has no way to distinguish progress from breakage using CI alone. The
> **scripts** are the feedback loop; CI is a final check.

If you want a green baseline instead, the move is to ship one module implemented as a worked
example and leave four empty. You lose some signal — the example anchors style, and candidates
imitate it — but candidates get a working loop from minute one and a reference for the interface.
Pick deliberately; do not end up in the middle, where CI is red *and* the README claims candidates
should keep it green.

## Related

- [harness-and-fairness.md](./harness-and-fairness.md) — the scripts and CI that implement all of
  this, and the seven ways the shipped version mis-graded.
- [azure-private-app-pattern.md](./azure-private-app-pattern.md) — choosing the components, and the
  per-technology asymmetries.
- [develop-infrastructure](../../develop-infrastructure/SKILL.md) — what good looks like in the
  architecture you are grading.
