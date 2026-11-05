# The findings log

> **Source.** `[repo]` — format and examples from a production data pipeline's 64-finding review,
> maintained alongside its [decision register](./register-format.md) for several months.
> `[deduced]` marks generalisation advice the document does not itself state.

A findings log is the register's companion. The register answers *why is this value what it is*; the
log answers *what is wrong, how sure are we, and has it actually been fixed*. Keeping them separate
matters: a decision describes a **choice**, a finding describes a **defect**. Merging them produces a
document that is neither auditable nor actionable.

## Document header

```markdown
# Project review — <system>

> Purpose: a single, citable record of what this pipeline does well, what is defective, and what
> could not be determined from the source, so that remediation can be argued about and tracked
> rather than rediscovered.

**Status:** living · **Last updated:** <date> · **Last verified:** <date> — <narrative of what
changed and on what evidence> · **Covers:** `src/`, `databricks.yml`, `resources/`, …
```

Two phrases in that purpose line do real work:

- **"what could not be determined from the source"** — the log has a place for *unknowns*, not only
  defects. Without it, anything unobservable silently becomes a non-finding.
- **"argued about and tracked rather than rediscovered"** — the log exists to stop the same defect
  being re-found every six months by a new reader.

## The "how to read this" section

Put the grading schemes at the top, before any finding. A reader who meets `**High** · [PROBABLE]`
without having seen the key will substitute their own meanings.

### Severity — about consequence

| Severity | Meaning |
|---|---|
| **Critical** | Produces a wrong answer silently, in the product's core function |
| **High** | Causes data loss, or prevents detection of a wrong answer |
| **Medium** | Degrades reliability, performance or maintainability |
| **Low** | Hygiene; worth fixing, not urgent |

Note that **Critical is defined by silence**, not by blast radius. A crash is recoverable because you
know it happened; a confidently wrong number is not. That definition is what makes the scale useful
in a data system, where the default failure is a plausible answer.

### Confidence — about evidence

Separate from severity, and only for findings about *runtime* behaviour:

| Grade | Meaning |
|---|---|
| **CONFIRMED `<date>`** | Observed. Either the source says so unambiguously at the lines cited, or someone ran something and reported the result |
| **[PROBABLE]** | The mechanism is established from the source, but whether it fires depends on a runtime fact nobody has observed |
| **[SUSPECTED]** | Inferred from configuration or a plausible reading; no mechanism established, no observation |

> **The rule that makes the grades honest.** *A grade may only rise on evidence of the matching
> kind. Reading more source cannot lift a finding to CONFIRMED when what is missing is an
> observation.*

That single sentence is the most transferable idea in this chapter. Without it, confidence inflates
through re-reading: each pass over the code feels like new evidence, and a suspicion becomes a fact
without anyone observing anything. **Name what kind of evidence is missing**, and the grade stops
moving until that kind arrives.

State the environment limits plainly in the same section — "nothing here was confirmed against a
running pipeline, because this development environment cannot authenticate to the workspace" — so
that `[PROBABLE]` is read as a property of the setup rather than of the author's diligence.

## The entry

```markdown
### 4.1 R4 — A failed pagination window is skipped permanently · **Critical**

Resume state lives in an `offsets` Delta table, recomputed each run as `max(request_offset_end)`
filtered on `request_success` (`01-01:245-268`).

If windows at offsets 100–200 and 300–400 succeed while 200–300 fails in the same run, the maximum
successful offset is 400. The next run starts at 400. **The 200–300 range is never revisited.**
Documents in that range are absent from the platform, and nothing records that they should have
been there.

The code acknowledges this at `01-04:319`: *"A failed middle window during concurrent pagination is
skipped … and never retried. Only matters if you need strict completeness."* Strict completeness is
a stated requirement of this service, so it matters.

Only a failure in the highest-offset window of a run is self-healing, because nothing later
establishes a higher maximum.

**Addressed 2026-09-16, pending workspace verification.** The resume rule now reads every attempt
rather than successes only, and never advances past the earliest window still outstanding. …
**The Spark half has not been executed** — see Q18.

**It could not be, and now it can.** Q30 established on 2026-09-18 that the `offsets` table was
empty, so the maintenance merge had never run — **R58**, which left this remediation written, tested
and inert. R58 was fixed and verified the same day. **Q18 is therefore askable for the first time.**
```

Anatomy worth copying:

| Element | Why |
|---|---|
| `R<n> — <assertive one-line claim>` | The heading states the defect, not the area. "A failed pagination window is skipped permanently" beats "Pagination issues". |
| A **worked numeric example** | 100–200 and 300–400 succeed, 200–300 fails, next run starts at 400. Concrete beats abstract for getting agreement. |
| The consequence in bold | One sentence a non-engineer can act on. |
| **Quote the code's own admission** | Where a comment concedes the defect, quoting it ends the argument about whether it is real. |
| The self-healing boundary | Saying precisely *when the defect does not bite* is what stops over-correction. |
| Remediation appended, not substituted | The original claim stays readable; the fix is a new paragraph with its own date and its own open items. |
| An explicit "inert remediation" note | A fix that was written but could never have run is its own finding. |

## Three IDs, three jobs

| Prefix | Holds | Lives in |
|---|---|---|
| `D<n>` | A decision: a value or choice, with its rationale verdict | decision register |
| `R<n>` | A finding: something wrong, with severity and confidence | findings log |
| `Q<n>` | An open question: something unknowable without an observation someone must go and make | open-questions log |
| `W<n>` | A work item: the remediation that settles one or more of the above | remediation plan |

Keeping `Q` separate from `R` is the subtle one. "We don't know whether the offsets table is
populated" is not a defect — it is a *measurement nobody has taken*. Filing it as a finding either
overstates it or gets it closed as unproven. Filing it as a question gives it an owner and a verb.

The four cross-reference constantly, and that is the point:

- a finding **cites** the decisions that caused it (`D47 already graded that setting unjustified for
  this stage`);
- a decision **cites** the finding that settled it (`Resolved for 02-02 on 2026-09-19: the copied
  value was the cause of R63`);
- a question **names** the finding it would upgrade or kill;
- a work item **names** everything it closes, so "done" is checkable.

## The evidence lifecycle

A finding moves through states, and the log records each transition **with its date and its
evidence**, appending rather than rewriting:

```
raised from source
  → [SUSPECTED] / [PROBABLE] / CONFIRMED          (grade set by evidence kind)
  → MEASURED <date>: <the number>                 (an observation exists)
  → REMEDIED <date>, UNOBSERVED                   (fix shipped, not yet seen running)
  → REMEDIED AND VERIFIED <date>                  (fix seen working)
  → closed
```

Two states earn their awkward names:

- **`REMEDIED … UNOBSERVED`** — the fix is merged and nobody has watched it work. Collapsing this
  into "fixed" is how an inert remediation survives for weeks. The log that invented this label
  found exactly that: a correct, unit-tested fix that could never execute because an upstream table
  it depended on was empty.
- **`RECONCILED <date>: <figure>`** — a finding that asked "how bad is it?" and now carries the
  answer in its own heading (`0.06%`). The number belongs in the title because that is what people
  quote.

Record corrections as prominently as findings. When a claim turns out to be wrong, say so in the
header narrative: *"one claim in it was then measured false and corrected — the vendor does serve
`DE` and `FR`, and the earlier statement came from reading a sampled warehouse table as if it
described the vendor."* Naming the **class of mistake** — mistaking a sample for the population — is
what stops it recurring.

## Pre-register the falsification threshold

The strongest habit in this log, and the easiest to adopt:

> Before running the query that tests a hypothesis, write down the number that would **refute** it.

From the source log: a hypothesis that an OOM was caused by line-heavy documents "was given a
falsification threshold of 2.5M lines before the query ran, and the query **falsified it**: the
corpus maximum is 211,334 lines". Elsewhere: "Query F tests it, with its threshold recorded first",
and a confirmation that explicitly notes it "match[ed] all three criteria recorded before the
query".

Why it works: debugging under pressure makes every result look confirmatory. A threshold written
first converts the query from a search for support into a test that can fail — and a hypothesis that
has survived a recorded threshold is worth far more than one that merely has examples. `[deduced]`
Record the falsified hypotheses too; they are the cheapest way to stop a colleague re-running the
same dead end.

## Separating a cause from a multiplier

When several mechanisms contribute to one symptom, grade their roles rather than listing them flat:

> "It is a contributing **multiplier** to R63, not its established cause."

And when measurement redirects the diagnosis, say what was eliminated:

> "R63's cause separated by measurement the same day: document size over 261,259 rows, max 7.79 MB,
> so **row count rather than row size**."

> "The remedy went into what a worker *holds* rather than what a batch *contains* — the distinction
> that matters, because rows per file are capped at 900 while bytes per file reach 318.4 MB, so a
> batch cannot be bounded below one file."

That last pattern — **naming the axis the fix acts on** — is what lets a reader tell a real fix from
a setting that was changed because it was nearby. Four attempts failed on this finding before the
fifth measurement identified the axis; the log records all five, which is why the fifth was right.

## The summary section

Lead with the findings that are **silent**, grouped by what they have in common rather than by
severity:

> "Five defects stand out because they are silent. None raises an error, fails a run, or sends an
> alert; all five produce a confident, wrong answer."

Then name the structural cause if there is one. The source log's is a model of concision:

> "Underneath them sits a structural cause: **no quality expectation in this repository can fail
> anything.** Every one uses bare `expect_all`, which records a metric and passes the row through.
> The pipeline is extensively instrumented and entirely unguarded."

Also worth copying: **say what the system does well, first and specifically.** The source log opens
by praising the request-envelope pattern by name. A review that is only negative gets read as an
attack and discounted; one that identifies a genuine strength has established that it is reading
carefully.

And where several findings are one failure at different depths, say so — "four findings describe one
failure at four depths" — then name the depth each occupies. Otherwise they get fixed individually
and the failure survives.
