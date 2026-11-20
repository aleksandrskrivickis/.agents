---
name: hiring-test-infrastructure
description: 'Use when creating, running, reviewing or repairing a take-home infrastructure-as-code exercise — an Azure/IaC hiring test completed in a few hours. Carries a complete build recipe that recreates the scaffold in an empty repository: every file in order, harness defects already fixed. Covers the composition-root-plus-empty-modules scaffold (the root references modules the candidate must create, so the compile error is the brief), one module per distinct skill, Bicep/Terraform/ARM tracks and keeping them at parity, subscription-scope roots that create their own resource group, gating deploy behind a comment, the per-track validate/plan/deploy scripts, the CI lint matrix, the Codespaces devcontainer, a weighted rubric, and the harness defects that silently mis-grade: unpinned linters across cohorts, checks that never reach the candidate''s code, double-muted security gates, plan artifacts the gitignore misses, a track that cannot pass.'
---

# A take-home IaC exercise: design, harness, and grading

> **What this is.** How to build and run a practical infrastructure-as-code hiring test — the
> scaffold a candidate clones, the harness that judges it, and the rubric a reviewer applies.
> Distilled from an Azure exercise (private-by-default App Service + Cosmos DB + Key Vault) that
> went through several rejected designs before settling, plus an audit of the shipped scaffold which
> found seven harness defects that would each have cost a candidate marks for the author's mistake.
>
> The exercise-design half is **technology-agnostic** — the scaffold technique, the module↔skill
> mapping and the fairness rules apply to any IaC stack. The Azure half is specific. It does **not**
> re-explain private-link mechanics, NSG rules or Bicep idiom: those are
> [develop-infrastructure](../develop-infrastructure/SKILL.md), and a reviewer grading the
> architecture should read that skill, not this one.

## Detailed references

- [build-the-scaffold.md](./references/build-the-scaffold.md) — **the build recipe.** Every file in
  creation order, the five-module interface table, the corrected CI and devcontainer, the
  broken-submission self-test, and every divergence from the source scaffold.
- [exercise-design.md](./references/exercise-design.md) — the composition-root-plus-empty-modules
  scaffold and the two designs rejected on the way to it, mapping one module to one skill, the
  time-box, gating the deploy step, and the green-baseline trade-off this design deliberately makes.
- [harness-and-fairness.md](./references/harness-and-fairness.md) — the per-technology scripts, the
  CI lint matrix and the devcontainer, plus the seven defects found in the shipped scaffold and what
  each one does to a candidate's score.
- [azure-private-app-pattern.md](./references/azure-private-app-pattern.md) — the target
  architecture, why Key Vault is the *easier* private-endpoint teaching resource than Storage, the
  Cosmos quirks worth knowing before you grade, and why the ARM track needs different treatment
  from the other two.

## The scaffold in one idea

The composition root is written; the modules it references **do not exist**. The candidate creates
them.

```
infra/bicep/main.bicep          # targetScope='subscription'; creates the RG;
                                # module network './modules/network/main.bicep' = { … }
infra/bicep/modules/network/    # <- empty, just a .gitkeep
                   private-dns/
                   keyvault/
                   cosmosdb/
                   webapp/
```

That one decision does most of the work:

- **The interface is fixed by the author.** Module names, which parameters go in, which outputs come
  back out, and the dependency order are all already declared in the root. You grade implementation,
  not naming taste, and every submission is comparable.
- **The compile error is the brief.** `az bicep build` fails with "module not found" five times.
  That list *is* the task list, and it shrinks as the candidate works.
- **Three technology tracks cost almost nothing.** One root per technology — Bicep, Terraform, ARM —
  each referencing the same five module names. No per-technology stub duplication; the candidate
  deletes the trees they do not use.

→ Deeper, including the two designs this replaced:
[exercise-design.md](./references/exercise-design.md).

## Recreating it in an empty repository

Follow [build-the-scaffold.md](./references/build-the-scaffold.md) top to bottom. It is ordered so
the repository is complete and verifiable at the end, and it ships the harness **already
repaired** — the seven defects in
[harness-and-fairness.md](./references/harness-and-fairness.md) are fixed, with each divergence
listed so you can revert any of them on purpose.

The short version, if you want the shape before the detail:

1. **Decide five things** — name prefix, region, which tracks, the time-box, and whether the
   security linter gates. They are threaded through every file.
2. **Write the module interface down once** — five modules, their inputs, their outputs. Every
   track's root implements that one table, or the tracks are not comparable.
3. **Create the tree**, with a `.gitkeep` in each empty module folder so it survives the clone.
4. **Write the roots** — subscription-scope Bicep and an `azurerm_resource_group` Terraform root, so
   the IaC creates its own resource group and there is no pre-step.
5. **Write the harness** — one linear script per track with `set -euo pipefail` and the deploy block
   commented out; CI that discovers files by content and prints how many it found; a devcontainer
   that fails when the toolchain is incomplete.
6. **Write the brief**, stating the time-box, that the empty folders are the task, that **CI is red
   until the last module lands**, and which checks gate versus inform.
7. **Break it on purpose and confirm every check fires.** This is the step that finds everything
   else, and it is not optional.

Default to **Bicep and Terraform only**. The ARM track needs a published artifact location to work
at all, so offering it unresolved hands one group of candidates a wall the others never meet.

## The rules that keep the exercise fair

1. **One module, one distinct skill, no repeats.** Five modules mapping to five different
   competencies beats eight modules testing three. If two modules exercise the same skill, cut one
   and spend the candidate's time elsewhere.
2. **Pin every tool the grading depends on.** A `latest` linter means cohort A and cohort B are
   graded by different rules, and you will not notice. Pin the IaC CLI, the linter, the provider
   (commit the lock file) and the container image.
3. **Every check must be able to reach the candidate's code.** A CI step that only ever walks the
   root directory cannot validate the modules — and it will report success while doing nothing. Test
   the harness against a *deliberately broken* submission before you ship it.
4. **A muted gate is not a gate.** `continue-on-error` plus `soft_fail` on the same job means the
   rubric line "linter findings addressed" has no evidence behind it. Decide whether the check gates
   or informs, and write the rubric to match.
5. **The harness must not create files the candidate gets marked down for committing.** If a script
   writes a plan file, the `.gitignore` must cover it — before you grade anyone on git hygiene.
6. **Keep the stated contract and the actual behaviour identical.** A README that promises
   `set -euo pipefail` and scripts that lack it is the author failing their own code-quality
   criterion, and candidates reason from the README.
7. **Gate the deploy step behind a comment, not a flag.** Candidates iterate offline for free, and
   nobody deploys to your subscription by accident. A commented block is also self-documenting in a
   way a `--dry-run` default is not.
8. **Let the IaC create its own resource group.** A subscription-scope root (or
   `azurerm_resource_group`) removes the "run `az group create` first" prerequisite, which is one
   fewer undocumented step between a candidate and a working plan.
9. **Check every technology track can actually pass.** Offering a choice you have not completed
   yourself is a trap. The ARM track in the source scaffold cannot deploy with the script it ships
   with — see [azure-private-app-pattern.md](./references/azure-private-app-pattern.md).
10. **Grade from the git history as well as the diff.** It is the only evidence of how someone works
    — and if you say you will read it, the rubric has to reward atomic commits rather than just
    mention them.

## Quick symptom → fix index

| Symptom | Likely cause / fix | Reference |
|---|---|---|
| Candidates ask what the modules should be called | The root does not declare the interface — put names, inputs, outputs and order in the composition file | exercise-design |
| Submissions are not comparable to each other | The brief left the module boundaries to the candidate | exercise-design |
| Two cohorts score differently on identical code | An unpinned linter or provider — pin and commit the lock file | harness-and-fairness |
| CI is green and the modules are broken | The check never walks into the module directories | harness-and-fairness |
| Security findings never fail anything | `continue-on-error` *and* `soft_fail` on the same job | harness-and-fairness |
| A script runs plan after validate already failed | No `set -euo pipefail`, despite the README promising it | harness-and-fairness |
| Candidate committed a plan file and lost marks | The harness writes it and `.gitignore` does not cover it | harness-and-fairness |
| Codespace reports success, first script fails | `set -euo pipefail` cancelled by `\|\| true` on every line | harness-and-fairness |
| A tool the README promises is missing locally | The devcontainer never installs it; CI has it and the candidate does not | harness-and-fairness |
| One technology's candidates all stall at deploy | Linked templates need an HTTPS-reachable artifact location | azure-private-app-pattern |
| "Private endpoint exists but still resolves public" | The DNS zone group is missing — grade this, it is the classic error | develop-infrastructure |
| Candidate created one endpoint for a multi-sub-resource service | Each sub-resource needs its own endpoint **and** its own zone | azure-private-app-pattern |
| The exercise feels too hard to finish in the time-box | Cut a module rather than a requirement; a half-built module grades worse than an absent one | exercise-design |
| Starting a new exercise from nothing | Follow the build recipe in order; do not improvise the interface table | build-the-scaffold |
| Two tracks disagree about a module's inputs | The interface table was written per track instead of once | build-the-scaffold |
| A CI job passes having checked no files | The discovery expression matched nothing and still exited zero — print the count | build-the-scaffold |

## Commands

```bash
# What a candidate runs — one script per technology, linear, no arguments
./scripts/bicep.sh          # az bicep build -> az bicep lint -> (what-if, create: commented)
./scripts/terraform.sh      # fmt -check + init -backend=false + validate + tflint -> (plan, apply: commented)
./scripts/arm.sh            # az bicep decompile -> arm-ttk -> (what-if, create: commented)

export AZURE_LOCATION=westeurope   # defaults inlined at the top of each script
export NAME_PREFIX=iactest         # also the RG suffix: rg-iactest
```

```bash
# What a reviewer runs before trusting the harness
bash -n scripts/*.sh                      # syntax only; it will NOT catch a missing set -euo pipefail
grep -L 'set -euo pipefail' scripts/*.sh  # which scripts silently continue past a failure
find infra -type d -name modules          # does CI's discovery expression actually reach these?
git log --oneline --stat                  # the history is half the signal
```

## Upstream documentation (sources)

- Subscription-scope deployments: <https://learn.microsoft.com/azure/azure-resource-manager/templates/deploy-to-subscription>
- App Service VNet integration: <https://learn.microsoft.com/azure/app-service/overview-vnet-integration>
- App Service Key Vault references: <https://learn.microsoft.com/azure/app-service/app-service-key-vault-references>
- Private endpoints overview: <https://learn.microsoft.com/azure/private-link/private-endpoint-overview>
- ARM-TTK: <https://github.com/Azure/arm-ttk>
- Azure Verified Modules: <https://aka.ms/avm>

## When to use this skill

- Designing a take-home IaC exercise, or cutting an existing one down to a realistic time-box.
- Auditing a scaffold before a cohort uses it — the fairness rules above are a checklist.
- Reviewing a submission: what to weight, what to forgive, and which failures are the author's
  rather than the candidate's.
- Repairing a harness that reports green while checking nothing, or red for reasons the candidate
  cannot act on.

## Related skills

- [develop-infrastructure](../develop-infrastructure/SKILL.md) — the real-world version of the
  architecture being tested: private endpoints and DNS zones in full, NSG rules, Bicep at
  subscription scope, `prevent_destroy`, and the Azure DevOps pipelines around it. Read this to
  grade the architecture.
- [workflows-github](../workflows-github/SKILL.md) — the lint-and-test workflow the CI matrix is a
  variant of, and how merges actually get gated.
- [workflows-devops](../workflows-devops/SKILL.md) — why `continueOnError` on a producing task
  relocates its failure, which is the general form of two defects in this harness.
- [write-technical](../write-technical/SKILL.md) — the brief is read under time pressure by someone
  who has never seen the repo; it is worth the same care as the code.
