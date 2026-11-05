# The decision-entry format

> **Source.** `[repo]` — the format and all worked examples are taken from a production data
> pipeline's 70-entry decision register. `[deduced]` marks generalisation advice that the register
> itself does not state.

## Document header

The register opens with a purpose line, a status block, and the rules it judges itself by. All three
matter: the purpose line stops it drifting into a design doc, the status block is how a reader
decides whether to trust it, and the rules are what make two compilers of the register agree.

```markdown
# Decision Register

> Purpose: record every tunable constant, threshold, algorithm choice and structural decision
> embedded in this pipeline, together with whatever rationale actually exists for it. Most entries
> have no recorded rationale, and this document names them rather than hiding them.

**Status:** living · **Last updated:** 2026-09-18 · **Last verified:** 2026-09-18 — D70 added for
R62's allowlist rule, and every `01-00` and `databricks.yml` citation re-validated against the files
afterwards *by content rather than by offset*, since both changed length. Earlier: D69 added for
R58's fix and D14's rationale corrected against it · **Covers:** `src/pipeline/`, `src/utils/`,
`databricks.yml`
```

Three things to copy from that header:

- **"Most entries have no recorded rationale, and this document names them rather than hiding
  them."** Stating the expected outcome up front stops the register being read as an indictment.
- **`Covers:`** — an explicit scope. Without it, every reader wonders whether the absence of an entry
  means "fine" or "not looked at".
- **The verification narrative.** Not just a date: *what* was re-checked, and *how*. "By content
  rather than by offset" is the detail that tells you the citations are trustworthy.

## The entry

Each entry is a heading carrying a stable ID, then a two-column table. The table shape is load-
bearing: it forces every field to be filled, and an empty cell is visibly empty.

```markdown
### D4 — Response size cap and the synthetic 513 status

| | |
|---|---|
| **Current value** | `max_response_bytes = 12 * 1024 * 1024` (12 MB). The body is read in chunks and the transfer is abandoned once the cap is passed; the row is stamped `request_status_code = 513` and the payload discarded. |
| **Where** | `src/utils/client.py:91`, enforced at `:352-367` |
| **Rationale on record** | None recorded for 12 MB. The comment `# 12 MB cap on a single response body` restates the value. 513 is documented only as a shape (`_envelope` docstring, `:234`), not as a chosen code. |
| **Risk if wrong** | Documents larger than 12 MB are **dropped permanently and never retried** — the offsets rebuild advances past them because the row carries `request_success = false`. For a service whose stated goal is holding the full text of every in-scope document, this is silent content loss. 513 is also not a registered HTTP status, so downstream consumers cannot interpret it without the producing system. |
| **Status** | Unjustified — needs an owner |
```

### Field by field

| Field | Rule |
|---|---|
| **Heading** | `### D<n> — <short noun phrase>`. The phrase names the decision, not the value, so the heading survives a value change. |
| **Current value** | The literal value, plus the mechanism if the value alone is uninterpretable. Include units. |
| **Where** | Every site, `file:line`. Multiple sites listed, not just the definition — see *citation hygiene* below. |
| **Rationale on record** | Quote the actual comment/docstring/description. Then judge it: `None recorded`, `Partial: …`, or `Recorded: …`. Never paraphrase a weak comment into a strong one. |
| **Risk if wrong** | What breaks, how loudly, and what else it touches. This is the longest field in a good entry. |
| **Status** | Exactly one of Justified / Assumed / Unjustified — needs an owner. |

Optional fields that earn their place when relevant:

| Field | Use when |
|---|---|
| **Precondition** | The decision only holds if something external is true (an endpoint exists, a table is populated). Include the command that checks it. |
| **Measured `<date>`** | A number was actually observed. Put the measurement here, not in the rationale — rationale is what was *recorded at the time*, measurement is what you found *later*. |
| **Why it was not the fix** | A plausible remedy was investigated and rejected. Recording the rejection stops the next person re-running the experiment. |
| **Revisit when `<X>`** | A pending change would make this entry re-decidable. Name the trigger, not a date. |

## Rationale vs restatement

The judgement that makes or breaks a register. A comment counts as rationale only if it explains
**why this value** rather than another. It does **not** count if it:

- restates the value (`# 12 MB cap on a single response body`);
- names the mechanism (`# retried with backoff (edge/transient)` against a set of status codes);
- describes what the code does (`# Filter out slices that are only a header marker`);
- justifies the *unit* but not the *magnitude* (`# 3000 is roughly equivalent of one MS Word page`
  — that is **Partial**, and the honest status is *Assumed*).

Worked examples at each level:

**Unjustified.** Nothing explains the membership of the set, and the comment labels rather than
argues:

```markdown
| **Current value** | `frozenset({403, 429, 500, 502, 503, 504})` |
| **Rationale on record** | None recorded. The trailing comment reads `# retried with backoff (edge/transient)`, which labels the set rather than justifying its membership. |
| **Risk if wrong** | 403 is normally a permanent authorization failure, not a transient one. Retrying it burns the retry budget and delays a hard failure. The same code is separately asserted as a defect by the `request_forbidden` expectation, so the pipeline retries a condition it also declares invalid. |
| **Status** | Unjustified — needs an owner |
```

Note what the risk field found: the system **retries a condition it elsewhere declares invalid**.
That contradiction was invisible until two decisions were written down next to each other. This is
the register's main yield — not the individual entries, but the contradictions between them.

**Assumed.** The trade-off is stated honestly, neither end is quantified:

```markdown
| **Current value** | `_READ_CHUNK_BYTES = 64 * 1024` |
| **Rationale on record** | Partial, and it states the trade-off honestly: "Small enough that an oversized body is abandoned promptly, large enough that ordinary responses cost few iterations." Neither end of the trade-off is quantified, so 64 KiB is a plausible default rather than a derived one. |
| **Status** | Assumed |
```

**Justified.** External constraint named, unit stated, margin explained, independently checkable:

```markdown
| **Current value** | `MAX_REQUEST_BYTES = 8 MiB` against a stated 16 MiB endpoint limit; a single oversize text is truncated to the budget |
| **Rationale on record** | Recorded: "Model serving rejects any request body over 16 MiB. The budget is measured on UTF-8 bytes and left well below the cap so JSON escaping and envelope overhead still fit." The 50% margin is generous, but the constraint is named and the reasoning is checkable. |
| **Risk if wrong** | Truncation is silent — the row is still stamped `request_success = true`, so a truncated embedding is indistinguishable from a complete one. With the current chunk size no single slice approaches 8 MiB, so the path is effectively dead code today. |
| **Status** | Justified |
```

A *Justified* entry can still carry a serious risk. The status judges the **rationale**, not the
safety of the decision. Keep those separate or the label becomes meaningless. `[deduced]`

## Supersession, not deletion

When a decision is replaced, strike the heading and keep the body. Citations elsewhere still point
at the ID.

```markdown
### D19 — ~~The vendor's `version` integer is the sole version-ordering signal~~ · **replaced 2026-09-18 by W12**
```

And in the tiering table, the retired row stays, struck through, with what remains of it:

```markdown
| ~~D19~~ | ~~Vendor `version` as the sole change signal~~ | **Settled 2026-09-18 by W12** — the pipeline's own content hash is the signal now. What remains from this row is D56's collision question, now that a hash decides something. |
```

That last clause is the pattern worth copying: **closing a decision usually leaves a residue**, and
naming the residue stops it being lost with the entry.

Entries added later keep their discovery order, so a register's numbering is not its section order —
`D68`, `D69` and `D70` sit inside sections 3, 1 and 1 respectively. Mark them `· **new <date>**` so a
returning reader can find what moved.

## Citation hygiene

Line numbers rot. Three habits keep them usable:

1. **Cite every site, with ranges for enforcement points.**
   `` `src/utils/client.py:91`, enforced at `:352-367` `` — definition and use are different facts.
2. **Re-validate by content after any edit that changes file length.** Search for the code the
   citation describes; do not trust the number. Record that you did it in the header.
3. **Prefer a searchable anchor where the line will move.** A symbol name or a distinctive string is
   stable in a way `:147` is not. `[deduced]`

A register whose pointers are wrong teaches readers to skip the *Where* field, which removes the
only thing making the entry actionable.

## Tiering: turning a list into a queue

A closing section ranks the unowned decisions **by consequence of being wrong**, not by how many
there are. Three tiers, with a one-line reason each — the reason is what makes the ranking
arguable, and therefore useful.

```markdown
## Decisions most urgently needing an owner

**Tier 1 — the correctness of the product depends on them, and no evidence exists.**

| ID | Decision | Why it comes first |
|---|---|---|
| D38, D39 | `SIMILARITY_THRESHOLD = 0.8` and the five change bands | These produce the pipeline's user-facing output. Marked `# TODO: Data science`. No evaluation set, no labelled examples, no precision or recall figure exists. |
| D28 | Legal-structure separators written then disabled | A legal-change pipeline recognises no legal structural markers when splitting. Disabled for unmeasured "performance"; nothing records what accuracy was traded away. |

**Tier 2 — they systematically distort results, and the fix is known.**

**Tier 3 — operational decisions with no recorded requirement behind them.**
```

What makes the tiers work:

- **Tier 1 is about evidence, not severity.** A high-severity decision with a measurement behind it
  is not Tier 1; a medium-severity one resting on nothing is.
- **Tier 2 says "the fix is known"** — these are schedulable. Tier 1 items need a decision first.
- **Tier 3 names the missing requirement**, which is often the real finding: "sets detection latency
  at up to seven days, with no recorded latency requirement to check it against". The problem is not
  the cadence; it is that no one wrote down what cadence was needed.
- Group related IDs on one row (`D25, D26, D27 — together these define what a "clause" is`) when
  they are only decidable together.

## Documentation drift

Compiling a register is the only time anyone reads the code against its own documentation, so it is
the only time drift gets found. Collect it in a closing paragraph and **attach each correction to
the decision's owner** rather than filing it as separate documentation work:

```markdown
**Documentation drift found while compiling this register.** `CLAUDE.md` describes a shared
`dlt_params` dict with Change Data Feed and a bronze quality tag, where `src/utils/configuration.py`
defines only `table_properties` with one key, used once (D50); it lists the retry set without `403`
(D1); and it refers to `resources/pipeline.pipeline.yml`, which is `resources/pipelines.yml`.
Correcting these belongs with whoever takes D50.
```

The drift is evidence for the register's thesis: documented conventions that do not exist in the
code are worse than none, because a new developer goes looking for a pattern that is not there.
