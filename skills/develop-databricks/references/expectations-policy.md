# Expectations: choosing a policy, not just writing rules

> **Source.** `[repo]` — from a production Lakeflow pipeline carrying 21 expectation blocks across
> 11 source files, and the decision register and review that audited them. `[docs]` marks documented
> Databricks behaviour; `[deduced]` an inference.

Expectations are Databricks-only (not Apache SDP — see
[sdp-python-api.md](./sdp-python-api.md)). Writing them is easy; the decisions around them are where
pipelines go wrong, and they are almost never made deliberately.

## The three variants do completely different things

| Variant | Violating row | Run | Use when |
|---|---|---|---|
| `expect_all` | **written to the table**, counted in metrics | continues | You want observability and will tolerate bad rows |
| `expect_all_or_drop` | dropped | continues | The row is unusable and silence is acceptable |
| `expect_all_or_fail` | — | **update fails** | A violation means the pipeline's output is not publishable |

> **Picking one is a product decision, not a style decision.** It decides whether your quality rules
> can *stop* anything, and it is the single most consequential choice in this file.

### The default drifts to all-advisory, and nobody notices

In the source project **every one of 21 expectation blocks used bare `expect_all`**; there were zero
uses of `expect_all_or_drop` or `expect_all_or_fail` anywhere in the codebase. The review's
structural finding was blunt:

> "No quality expectation in this repository can fail anything. The pipeline is extensively
> instrumented and entirely unguarded."

That is a defensible position — but only if it was chosen. It is reached by default because
`expect_all` is what every example uses and because an advisory rule never wakes anyone up.

Two consequences worth stating before you accept it:

1. **A violating row is written exactly like a valid one.** Only a reader who inspects the event log
   learns otherwise.
2. **No column carries the verdict.** A consumer of the published table cannot distinguish a valid
   row from a flagged one, because the flag lives in pipeline metrics, not in the data.

If you want advisory rules *and* consumable quality signals, you have to materialise the verdict
yourself:

```python
# Keep the rule advisory, but make its outcome readable downstream.
@dp.table(name="documents", table_properties=table_properties)
@dp.expect_all({"content_present": "content IS NOT NULL AND length(trim(content)) > 0"})
def documents():
    return source.withColumn(
        "dq_content_present",
        F.col("content").isNotNull() & (F.length(F.trim("content")) > 0),
    )
```

The duplication is real and it is the price of an advisory policy. `[deduced]`

## Structure: two blocks, presence then value

The convention worth copying — it makes a 30-rule block readable and makes a missing rule obvious:

```python
dp.create_streaming_table(
    name="contents",
    expect_all={
        # 1. Column presence: when the request succeeds, every column must hold a
        #    non-null, non-empty value.
        "empty_document_id": "request_success IS NOT TRUE OR document_id IS NOT NULL",
        "empty_title": "request_success IS NOT TRUE OR (title IS NOT NULL AND length(trim(title)) > 0)",
        # 2. Value checks.
        "request_succeeded": "request_success = true",
        "request_forbidden": "request_status_code IS DISTINCT FROM 403",
        "jurisdiction_state_for_us": "jurisdiction_country <> 'US' OR jurisdiction_state IS NOT NULL",
    },
)
```

`dp.create_streaming_table` takes `expect_all={…}` as a keyword; `@dp.table` stacks two
`@dp.expect_all({…})` decorators instead, one per block.

## The four anti-patterns an audit found

### 1. Presence rules gated on success upstream, ungated downstream

Ingestion rules are correctly prefixed `request_success IS NOT TRUE OR …` — a failed call cannot be
expected to have populated its columns. Downstream tables then applied **the same rules without the
gate**, and the result was rules that fail on the overwhelming majority of rows *by design*:

> Every vendor date field — `expiration_date`, `date_of_repealed`, `date_of_decision` and five
> others — was required non-empty on every row. Most legal documents legitimately have no expiry or
> repeal date.

- **The rule:** when you copy an expectation block downstream, re-derive which columns are
  *genuinely* mandatory in that context. Optional-in-the-domain columns must not carry presence
  rules at all.
- **Why it matters more than it looks:** rules that always fail drown the ones that sometimes fail.
  A metrics panel at 97% violation is read as broken tooling, not as a data problem.

### 2. "Any retry counts as a failure"

```python
"request_retries": "request_retry_count = 0"      # ← reconsider
```

A retry that succeeded produced correct data. Flagging it conflates *"the vendor was briefly slow"*
with *"this row is wrong"*. Combined with retrying codes that are not actually transient, routine
behaviour permanently inflates the violation count and desensitises everyone reading it.

Prefer a rule that asserts the outcome, and a *separate* observability threshold on retry volume:

```python
"request_succeeded": "request_success = true",
"request_retries_bounded": "request_retry_count <= 2",   # a budget, not a prohibition
```

### 3. Enumerating status codes, duplicated per table

```python
"request_unauthorized":  "request_status_code IS DISTINCT FROM 401",
"request_forbidden":     "request_status_code IS DISTINCT FROM 403",
"request_not_found":     "request_status_code IS DISTINCT FROM 404",
# … eight more, repeated verbatim in five files
```

Low correctness risk, high maintenance cost — and it **had already drifted**: one of the five copies
checked four codes and omitted seven. A new status code must be added in five places to be caught.

Two fixes, and the second is better:

```python
# Generate the block once, in the shared utils package.
RETRYABLE = (401, 403, 404, 429, 500, 502, 503, 504, 513, 598)
STATUS_EXPECTATIONS = {f"request_status_{code}": f"request_status_code IS DISTINCT FROM {code}" for code in RETRYABLE}

# Or, better: assert success once and let the code be a dimension you group by.
{"request_succeeded": "request_success = true"}
```

Enumerating codes is only worth it if someone acts differently per code. If the panel just shows a
breakdown, `group by request_status_code` on the table gives you that without 10 rules per table.
`[deduced]`

### 4. Self-referential integrity checks

```python
"content_hash_matches_content": "content_hash = md5(content)"
```

This compares a column against a recomputation of itself **in the same row**, so it can only fail on
a Spark defect — it tests nothing about the data.

It becomes worth having the moment the hash is *load-bearing*: in the source project the hash later
became the exact-match join key and the change signal, at which point the expectation stopped being
circular and started guarding a contract. Two notes if you get there:

- MD5 carries no collision guarantee, and if the hash decides "changed vs unchanged", a collision
  means a changed document reported as unchanged. Nobody had looked for one.
- A hash computed in one stage and re-asserted in a *later* stage is a real check — same row, same
  stage is not.

## Where expectations cannot help

- **A left join with a non-null expectation on the right side** flags rows rather than preventing
  them. In the source project two ingestion stages advanced at different rates, so documents whose
  text had not yet arrived were written with a null body, flagged, retained (advisory policy), and
  then **skipped silently** by the next stage — producing zero downstream rows with no error
  anywhere. The expectation faithfully reported a condition nobody could act on.
  Fix the rate mismatch or make the join inner; do not expect an expectation to fix a topology.
- **Expectations do not see what never arrived.** No rule can flag a page the ingestion skipped.
  Completeness needs a reconciliation — compare what the source says it has against what landed —
  and that is a separate dataset, not an expectation.

## Checklist for a new expectation block

1. Which variant? Say why, in a comment, once per pipeline rather than per rule.
2. Presence rules: gated on upstream success? Only for genuinely mandatory columns?
3. Value rules: do they assert outcomes rather than enumerate mechanisms?
4. Is any rule guaranteed to pass (self-referential) or guaranteed to fail (optional column)?
5. Is the block duplicated anywhere? If so, generate it from one place.
6. If the policy is advisory, does a column carry the verdict for downstream consumers?
7. Is there a completeness check somewhere, given that expectations cannot provide one?

## Related

- [sdp-python-api.md](./sdp-python-api.md) — the decorator/function surface and what is
  Databricks-only.
- [operations-and-refresh.md](./operations-and-refresh.md) — reading the event log, where expectation
  metrics actually land.
