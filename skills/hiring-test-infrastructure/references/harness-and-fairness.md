# The harness, and the seven ways it mis-graded

> **Source.** `[repo]` — an audit of the shipped scaffold's scripts, CI workflow, devcontainer and
> `.gitignore`. Every defect below was verified in the files, not inferred from the README.
> `[docs]` marks a vendor-documented behaviour; `[deduced]` an inference.

A take-home harness has an unusual property: **its bugs are charged to the candidate.** A check
that silently passes lets a weak submission through; a check that fails for a reason the candidate
cannot act on costs a strong one marks. So the harness deserves the same review as the exercise, and
the fastest way to get it is to run a *deliberately broken* submission through it and confirm every
check fires.

The shipped scaffold is a good scaffold with seven defects. They are worth going through
individually because each is a distinct class, and the classes recur in any harness.

## 1. The README promises `set -euo pipefail`; no script has it

The README states the scripts are *"plain `set -euo pipefail`, no flag parsing, no surprises"* and
that each *"runs validate → plan → deploy in order and stops at the first error"*. None of
`bicep.sh`, `terraform.sh` or `arm.sh` contains it. `[repo]`

The consequence is not cosmetic. In `bicep.sh`, a failing `az bicep build` does not stop
`az bicep lint`. Once the deploy block is uncommented, a failing validate does not stop `what-if`,
and a failing `what-if` does not stop `create` — so the script's one documented behaviour,
stopping at the first error, is exactly what it does not do.

```bash
#!/usr/bin/env bash
set -euo pipefail          # <- the line the README describes, missing from all three
```

Note that `bash -n scripts/*.sh` will not find this: the scripts are syntactically perfect. The
check is `grep -L 'set -euo pipefail' scripts/*.sh`.

The general lesson is the one the handbook already names in
[develop-databricks](../../develop-databricks/references/sdp-vs-databricks-and-naming.md) →
*documentation drifts faster than code*: **when the README and the code disagree, candidates reason
from the README**, so in a hiring test the drift costs someone else marks rather than you time.

## 2. CI's Terraform job never reaches the candidate's modules

```yaml
- name: terraform validate + tflint per module
  run: |
    set -e
    while IFS= read -r d; do
      if ls "$d"/*.tf >/dev/null 2>&1; then
        (cd "$d" && terraform init -backend=false && terraform validate && tflint)
      fi
    done < <(find infra -type d -name terraform)
```

`find infra -type d -name terraform` matches exactly one directory: `infra/terraform`. It does not
match `infra/terraform/modules/network` or any other module — those are named `network`,
`private-dns`, and so on. The step is called *"per module"* and never validates a module. `[repo]`

So the candidate's actual work is covered by `terraform fmt -recursive -check infra` — formatting —
and nothing else. Submissions with invalid module HCL pass this job, and the rubric's "CI is green"
row is satisfied by a job that checked the root only.

The fix is to discover by content rather than by directory name:

```yaml
done < <(find infra -type f -name '*.tf' -exec dirname {} \; | sort -u)
```

**The class:** a discovery expression that happens to match the one directory you tested it in.
Any `find … -name <literal>` driving a validation loop deserves a `| wc -l` check against what you
expect before you trust it.

## 3. The security gate is muted twice

```yaml
security:
  runs-on: ubuntu-latest
  continue-on-error: true        # mute 1 — the job cannot fail the run
  steps:
    - uses: bridgecrewio/checkov-action@master
      with:
        soft_fail: true          # mute 2 — the action cannot fail the job
```

Either line alone makes Checkov advisory; both together mean nothing about the security posture can
ever fail CI, while the rubric says *"linter findings addressed or justified"* and the requirements
say *"code passes the linters wired into CI"*. `[repo]`

Advisory is a legitimate choice — see
[workflows-devops](../../workflows-devops/SKILL.md), where keeping a linter advisory during a
migration is the recommended pattern. The defect is the **mismatch**: a rubric line with no
evidence behind it. Pick one:

- **It gates** → drop both mutes, and accept that you must fix the scaffold's own findings first.
- **It informs** → keep one mute, delete the other as redundant, and reword the rubric to *"read the
  Checkov output and justify what you left"* so the reviewer knows to look at the log rather than
  the badge.

Also note `checkov-action@master` — an unpinned action, which is the same problem as defect 4.

## 4. One tool is unpinned, and it is the one that grades

The scaffold is careful about versions almost everywhere:

| Tool | Where pinned | Deterministic? |
|---|---|---|
| Terraform | `1.9.5` in both the devcontainer and CI | yes |
| `azurerm` provider | `4.72.0` in the committed `.terraform.lock.hcl` | yes |
| Container image | `base:ubuntu-22.04` | yes |
| **tflint** | `tflint_version: latest` in CI, `"latest"` in the devcontainer | **no** |
| **checkov-action** | `@master` | **no** |

So two cohorts submitting byte-identical code can receive different lint findings, months apart,
with nothing in the repo recording why. `[repo]`

**Pin everything the grade depends on**, and treat the lock file as part of the harness rather than
a Terraform detail — committing `.terraform.lock.hcl` is what makes the provider half of this
deterministic, and it is already done correctly. Re-pin deliberately between cohorts if you want
newer rules, and note the bump in the repo so scores stay comparable.

## 5. `set -euo pipefail` cancelled by `|| true` on every line

```bash
#!/usr/bin/env bash
set -euo pipefail

az --version | head -n 1 || true
az bicep version || az bicep install
terraform -version | head -n 1 || true
tflint --version || true
pwsh -v || true
pwsh -NoProfile -Command "… Install-Module arm-ttk …" || true
```

Five `|| true` suffixes, and `set -e` now governs nothing. `postCreateCommand` always reports
success, so a Codespace with a missing or broken toolchain looks healthy and fails on the
candidate's first script run — at which point they are debugging your container on their time.
`[repo]`

`|| true` on a *version print* is reasonable: the output is informational. On the `Install-Module`
line it is not — that is the one step whose failure matters, and it is suppressed. Make the verifier
verify:

```bash
for tool in az terraform tflint pwsh; do
  command -v "$tool" >/dev/null || { echo "MISSING: $tool"; exit 1; }
done
```

**The class:** a strictness pragma contradicted line by line. `grep -c '|| true'` next to
`grep -c 'set -e'` in the same file is a one-second audit.

## 6. A promised tool is never installed

The README lists the devcontainer as providing *"`az`, `bicep`, `terraform`, `tflint`, `pwsh`,
`checkov`, `arm-ttk`"*. `post-create.sh` installs `arm-ttk` and verifies the rest. **Checkov is
never installed.** `[repo]`

CI runs Checkov; the candidate cannot. So the one linter they cannot execute locally is one they are
told to satisfy — and because it is also double-muted (defect 3), nobody notices the asymmetry from
either side.

**Rule:** the devcontainer and CI should run *the same* tool set. Where they diverge, the README has
to say which checks are CI-only and how to interpret them, or candidates optimise against a tool
they cannot see.

## 7. The harness writes a file `.gitignore` does not cover

`scripts/terraform.sh` writes a plan file:

```bash
# terraform -chdir="${TF_DIR}" plan -var … -out tfplan.bin
```

And `.gitignore` covers plan output only as a commented example:

```gitignore
# Include tfplan files to ignore the plan output of command: terraform plan -out=tfplan
# example: *tfplan*
```

So `infra/terraform/tfplan.bin` is untracked and **not ignored**. A candidate who runs the full
script and then `git add -A` commits it — and gets marked down under *"Git hygiene: no committed
secrets/state files"* for a file the harness told them to create. A plan file also contains
fully-resolved variable values, so the mark-down is substantively right and procedurally unfair.
`[repo]`

Uncomment the pattern. More generally: **enumerate every path the harness writes and check each one
against `.gitignore` before grading anyone on hygiene.** `.terraform/`, `*.tfstate*` and
`.terraform.tfstate.lock.info` are all correctly covered here — the plan file is the one that was
missed, and it is the one the scripts actually produce.

## The audit, as a checklist

Run this against any take-home harness before a cohort touches it:

1. Does every script fail fast, and does the README describe what the scripts actually do?
2. Does each CI check **reach the candidate's files**? Print what the discovery expression matched.
3. Is any gate muted? If so, does the rubric match its advisory status?
4. Is every version-bearing tool pinned — CLI, linter, provider lock file, actions, image?
5. Does the environment verifier actually fail when the environment is wrong?
6. Do the devcontainer and CI provide the same tools, and does the README say so truthfully?
7. Is every file the harness writes covered by `.gitignore`?
8. Does a deliberately broken submission fail every check you expect it to?

Item 8 is the one that finds the others. Commit a branch with an invalid module, an unformatted
file, a hardcoded secret and a committed plan file, push it, and read the CI output: anything that
stays green is a check you do not have.

## Related

- [exercise-design.md](./exercise-design.md) — the rubric these defects undermine, and the
  green-baseline trade-off that makes CI a weak signal here by design.
- [workflows-devops](../../workflows-devops/SKILL.md) — `continueOnError` on a producing task, the
  general form of defects 1 and 3.
- [workflows-github](../../workflows-github/SKILL.md) — the lint-and-test workflow this CI matrix is
  a variant of, and how merges get gated.
