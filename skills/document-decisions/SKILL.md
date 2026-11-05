---
name: document-decisions
description: 'Use when a system carries tunable constants, thresholds, algorithm choices or structural assumptions whose reasons are not written down — "why is the similarity threshold 0.8?", "why do we retry 403?", "why chunk at 3000 characters?" — or when auditing a codebase and needing somewhere to put the findings. Covers the decision register (stable IDs, current value, where, rationale on record, risk if wrong, Justified/Assumed/Unjustified status), the companion review/findings log (severity, SUSPECTED → CONFIRMED → MEASURED → REMEDIED → VERIFIED lifecycle, cross-references), how to tell a real rationale from a comment that merely restates the value, tiering what needs an owner first, and keeping citations from rotting. Distilled from a production data pipeline that compiled 70 decisions and 64 findings this way.'
---

# Recording engineering decisions

Every non-trivial system is held up by numbers nobody can defend. A similarity threshold of `0.8`.
A retry set that includes `403`. A chunk size of `3000`. Each was chosen once, for a reason that
made sense at the time, and the reason was never written down. A year later the number is load-
bearing and unauditable: nobody can change it, because nobody can say what it was protecting.

This chapter describes two paired artifacts that fix that, and the discipline that makes them worth
maintaining:

- a **decision register** — every tunable value and structural choice, with whatever rationale
  actually exists, and an honest verdict on whether that rationale is good enough;
- a **findings log** — the defects and risks found while compiling the register, tracked from
  suspicion to verified remedy.

> **Source.** Distilled from a production Databricks data pipeline that maintained a 70-entry
> decision register and a 64-finding review alongside the code for several months. The practice is
> domain-agnostic; the examples are not.

## Detailed references

- [references/register-format.md](./references/register-format.md) — the decision-entry format field by field, worked examples at each status level, how to tell rationale from restatement, the ID scheme, and tiering what needs an owner.
- [references/findings-log.md](./references/findings-log.md) — the findings-log format, severity, the evidence lifecycle, how a finding settles a decision, and the review-to-remediation handoff.

## The core idea

**A comment that restates the value is not a rationale.** This is the whole discipline in one
sentence, and applying it honestly is what makes a register useful rather than decorative.

```python
# 12 MB cap on a single response body
max_response_bytes = 12 * 1024 * 1024
```

That comment explains nothing. It names the value a second time. The questions it leaves open are
the ones that matter: why 12 and not 50? What happens to a document above the cap? Who decided?

Compare:

```python
# Model serving rejects any request body over 16 MiB. The budget is measured on
# UTF-8 bytes and left well below the cap so JSON escaping and envelope overhead still fit.
MAX_REQUEST_BYTES = 8 * 1024 * 1024
```

That is a rationale: it names an external constraint, states the unit, and explains the margin. It
is **checkable** — someone can go and verify the 16 MiB limit. The first comment cannot be checked
against anything.

A register that marks the first entry *Justified* because it has a comment is worse than no
register, because it launders an unknown into a reassurance.

## The three verdicts

Every entry gets exactly one:

| Status | Means | Test |
|---|---|---|
| **Justified** | A recorded reason explains the choice, and the reason is checkable | Could a stranger verify the reason without asking the author? |
| **Assumed** | A partial reason exists — a mechanism, a constraint, an analogy — but the specific value was never derived or measured | Is the *shape* explained but not the *number*? |
| **Unjustified — needs an owner** | Nothing on record explains it | Is the only "explanation" a restatement? |

The third label is doing the real work. It is deliberately uncomfortable, it names a person-shaped
gap rather than a documentation gap, and a register where most entries land there is **succeeding** —
it has converted invisible risk into a list someone can work through.

## The rules that make a register survive contact with a codebase

1. **One stable ID per decision, forever.** `D1`, `D2`, … assigned in order of discovery, never
   renumbered, never reused. Other documents, commit messages and code comments cite the ID. When a
   decision is superseded, strike the title through and say what replaced it — do not delete the
   entry, because the citations pointing at it are still out there.
2. **Record the value *and* its location.** `file:line` for each site. A decision applied in five
   places with four sites recorded is a decision you will half-change.
3. **Quote the rationale, don't summarise it.** Paste the actual comment or config description. If
   it turns out to restate the value, the quote makes that self-evident; a summary would hide it.
4. **Always fill in "risk if wrong".** This is the field that earns the register its keep. It is
   also where you discover that two decisions interact — that a page size interacts with a response
   cap, that a chunk size interacts with a model's context window. Write the interaction down in
   both entries.
5. **Separate the decision from the defect.** "The threshold is 0.8 and nothing explains why" is a
   decision (register). "Every embedding is computed on a truncated clause" is a finding (findings
   log). A register entry describes a *choice*; a finding describes something *wrong*. Cross-
   reference them; do not merge them.
6. **Re-validate citations by content, not by line offset.** Line numbers rot on the next edit. When
   a file changes length, re-find each citation by searching for the code it refers to, and say in
   the status line that you did. A register full of stale `:147` pointers trains people to distrust
   it.
7. **Date every verification, and say what you verified.** `Last verified: <date> — every citation
   in sections 3 and 4 re-checked against the files by content` is useful. `Last updated` alone is
   not: it tells you someone touched the document, not that its claims still hold.
8. **Tier the unjustified entries by consequence, not by count.** A register with forty unowned
   decisions is paralysing. Three tiers — *the correctness of the product depends on this and no
   evidence exists* / *this systematically distorts results and the fix is known* / *operational,
   no recorded requirement behind it* — turn it into a work queue.
9. **Name documentation drift when you find it.** Compiling a register means reading the code
   against its docs, which is the only time anyone does. Note every place they disagree, and attach
   the correction to whoever owns the decision rather than filing it separately.
10. **Keep it in the repo, next to the code.** A register in a wiki is a register nobody updates in
    the same commit as the value. `docs/decision-register.md` beside `src/` is one `git grep` away
    from the constant it describes.

## Quick symptom → action index

| Symptom | What it means | Action |
|---|---|---|
| "Why is this 0.8?" and nobody knows | Unregistered decision | Add an entry; status *Unjustified*; tier it |
| A comment exists but explains nothing | Restatement masquerading as rationale | Quote it verbatim, mark *Unjustified*, say why the comment doesn't count |
| Two constants must move together and nothing says so | Undocumented interaction | Record it in the "risk if wrong" of **both** entries |
| A value was tuned by trial and error across many commits | Assumed at best | Record the commit that set it; note that no measurement exists |
| A setting is cited as a control but has no effect | Inert configuration | Say so explicitly — a setting that cannot act is worse than an absent one, because it is cited as protection already in place |
| A mitigation was added, then a second one for the same failure | Possibly redundant | Record both and the open question of whether both are still needed |
| The register's line numbers don't match the code | Citation rot | Re-validate by content; note the re-validation in the status line |
| Forty entries all say *needs an owner* | No prioritisation | Add the three-tier ranking section |
| A decision is reversed | Supersession, not deletion | Strike the title, keep the entry, name the replacement and the date |
| Code and docs disagree | Drift found during compilation | Record it; attach the fix to the decision's owner |

## When to use this skill

- Auditing an inherited system, or onboarding onto one whose constants look arbitrary.
- Before changing a threshold, batch size, timeout or similarity cutoff — to find out what it was
  protecting.
- After a production incident caused by a value nobody could defend.
- When a reviewer keeps asking "why this number?" and the answer keeps being "it was like that
  when I got here".
- When preparing a system for handover, or for a claim someone else will act on — a coverage
  figure, an accuracy figure, a latency guarantee.

## Related skills

The pipeline this practice came from is documented across several chapters; its decisions are cited
throughout them:

- [develop-pyspark](../develop-pyspark/SKILL.md) — the performance and memory decisions (Arrow batch
  sizing, concurrency multipliers, chunking and embedding fit).
- [develop-sdp](../develop-sdp/SKILL.md) — the expectations policy, and why "every rule is advisory"
  is itself a decision needing an owner.
- [databricks-asset-bundles](../databricks-asset-bundles/SKILL.md) — the deployment defaults
  (schedules, retries, per-target limits).
