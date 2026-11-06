# Chunking documents, and making chunks fit the embedding model

> **Source.** `[repo]` — from a production pipeline that splits long documents into clause-level
> slices, embeds them, and diffs successive versions; plus the decision register and review findings
> compiled against it. `[docs]` marks documented library/model behaviour; `[deduced]` an inference.

Chunking looks like a configuration detail and behaves like a schema. Every downstream number — a
similarity score, a retrieval hit, a "this clause changed" verdict — is computed over units your
splitter invented. Get the units wrong and everything downstream is confidently wrong at the wrong
granularity.

## The two-stage splitter

Structure first, then characters as the fallback:

```python
from langchain_text_splitters import MarkdownHeaderTextSplitter, RecursiveCharacterTextSplitter

markdown_splitter = MarkdownHeaderTextSplitter(
    headers_to_split_on=[("#" * level, f"Header {level}") for level in range(1, 7)],
    return_each_line=False,
    strip_headers=False,  # keep the heading in the slice: it is context for the embedding
)

text_splitter = RecursiveCharacterTextSplitter(
    separators=[...],  # see "the ladder is the policy" below
    is_separator_regex=True,
    chunk_size=3_000,
    chunk_overlap=0,
)

sections = markdown_splitter.split_text(document_markdown)
slices = text_splitter.split_documents(sections)
```

`strip_headers=False` is the one to notice: the heading text travels with the chunk, so the
embedding sees "Article 12 — Termination" rather than an unlabelled paragraph. Retrieval quality
depends on it more than on the chunk size.

> **The load-bearing assumption nobody measures.** This design assumes the upstream conversion emits
> headings that correspond to real divisions of the document. Where a source has no headings, the
> entire document falls through to the character ladder and the boundaries become arbitrary. Measure
> **header coverage** (below) before trusting header-first splitting — in the source project nothing
> did, and it was logged as an unowned decision.

## The separator ladder *is* the splitting policy

`RecursiveCharacterTextSplitter` tries separators **in order** and only moves down the list when a
chunk is still too big. Ordering is therefore not a style choice; it is the policy.

A ladder descends from structural to desperate:

```python
separators = [
    r"(?:^|\n)ARTICLE\s+\(?\d+\)?",  # structural markers
    r"\d+\.\d+\s*",  # 1.1 sub-provision numbering
    r"\(\s*[0-9a-zA-Z]+\s*\)\s*",  # (a) / (1) / (2A) / (iv) parentheticals
    r"\n\|",  # table rows
    r"\n\n",
    r"\n",  # paragraph, line
    r"(?<=\.)\s+",
    r"(?<=。)",
    r"(?<=，)",  # sentence terminators, incl. CJK
    r"​",
    r"\s+",
    r"",  # zero-width space, whitespace, character-level
]
```

Two traps, both real:

- **A greedy numeric separator placed too high splits mid-sentence.** `r"\d+\.\s*"` — bare `1.`
  numbering — ranked above `\n\n` means *any* decimal followed by a period can become a boundary: a
  monetary amount, a date fragment, a cross-reference. The fix is to require the number to start a
  line (`(?:^|\n)`) or to rank it below the paragraph break. In the source project this sat above
  `\n\n` and was recorded as an unjustified decision. `[repo]`
- **Use `(?:^|\n)` on heading-style regexes**, not `^`. Without it the pattern only matches at the
  start of the chunk being split, not at every heading line inside it.

> **Disabling separators "for performance" is an accuracy change.** The source project wrote ~27
> regexes for domain structure (`PART`, `CHAPTER`, `SCHEDULE`, `ARTICLE`, `SECTION`, `ANNEX`,
> `RECITALS`, …), then commented them all out in a commit titled "Comment out heavy slicing rules
> for performance" — with no measurement recorded, no threshold that would justify re-enabling, and
> no assessment of what splitting quality was traded away. The system then split domain documents
> while recognising no structural marker above sub-provision numbering. If you disable separators for
> speed, record the before/after on the metrics below in the same commit.

## `chunk_size` and `chunk_overlap` are downstream decisions

**`chunk_size` sets the granularity at which change is reported.** Too large and a one-word
amendment scores as a near-identical block; too small and one logical unit fragments across chunks
that then compete in whatever matching step follows.

Justifying it by analogy is the common failure: *"3000 is roughly equivalent of one MS Word page"*
explains the **unit**, not the **magnitude**, and says nothing about the object you actually care
about. That is a weak justification at best.

**`chunk_overlap = 0` serves diffing and hurts retrieval.** Zero overlap gives clean, non-duplicated
units for exact-match comparison between document versions; it also means a sentence straddling a
boundary is cut, and neither half matches its predecessor cleanly or retrieves well. If the same
chunks feed *both* diffing and retrieval — which is common and was the case here — you have a
genuine conflict, and the right move is to say so explicitly rather than pick a number.

| Use | Wants |
|---|---|
| Version diffing / exact match | `overlap = 0`, stable boundaries, deterministic ids |
| Retrieval / RAG | overlap > 0, headings retained, chunk ≤ model context |
| Both from one table | Pick for diffing, then measure the retrieval cost — or materialise two chunkings |

## The failure that costs the most: chunk size exceeding the model's context

> **Silent truncation.** An embedding model whose context window is shorter than your chunk
> truncates the input and returns a perfectly well-formed vector. Nothing errors. Every score
> downstream is computed on the opening fragment of each chunk, and the output looks entirely
> correct.

In the source project this was a **Critical** finding: chunks of 3,000 characters (≈700–900 word
pieces, 90th percentile 5,041 characters) were embedded by a model with `max_seq_length = 256`
tokens. Every embedding in the corpus was computed on a truncated clause, for months, invisibly.

Check the fit explicitly, and re-check it whenever either side moves:

```python
# At registration/selection time, not at inference time.
assert model.max_seq_length * CHARS_PER_TOKEN >= P99_CHUNK_CHARS, (
    f"model window {model.max_seq_length} tokens cannot hold p99 chunk of {P99_CHUNK_CHARS} chars"
)
```

- **Budget ~3–4 characters per token** for English, fewer for CJK and for heavily inflected
  languages. Check against your **p99 chunk size**, not the mean — the mean always fits. `[deduced]`
- **Multilingual corpora need a multilingual model**, and the test is not "does it run". A strong
  English-only model with an 8k window "would truncate nothing while embedding German statute badly
  — the same defect wearing different clothes". If your separator ladder carries CJK punctuation,
  your model choice has already been made for you.
- **Choosing the model is choosing the window**, so record the window as the reason. A model chosen
  on benchmark scores alone will eventually be swapped for one with a shorter window by someone
  optimising a different metric.
- Request-size limits are a *separate* constraint from the context window — see
  [model-serving-and-batching.md](./model-serving-and-batching.md) for byte-aware batching.

## Give every chunk a deterministic id — and treat its format as a contract

```python
slice_id = concat_ws("-", col("document_id"), lpad(col("clause_index").cast("string"), 6, "0"))
```

- Zero-padding makes lexical order match numeric order, which matters the moment anything sorts by
  id.
- **If anything parses the id back, the format is a contract, not a label.** In the source project
  the downstream stage recovered each chunk's position with
  `split(slice_id, "-").getItem(1)` and used it for a positional penalty and for alignment ordering.
  Changing the separator or the padding would have broken change classification **silently** rather
  than failing. Either assert the format in a test, or carry the position as its own column and stop
  parsing the id.
- Six digits caps a document at 1,000,000 chunks with no check. Pick the width deliberately and
  assert it. `[repo]`

## Stamp chunks with the generation of the chunker that produced them

This is the single best idea in this area, and it generalises well beyond chunking.

> **A chunk is an artifact of the method, not a property of the document.** Two chunks are comparable
> only if the same method produced them. So the method needs an identity, and every chunk must carry
> it.

```python
# src/utils/slicing.py — the whole configuration is data, in one dict
SLICER_CONFIG = {
    "headers_to_split_on": HEADERS,
    "strip_headers": False,
    "return_each_line": False,
    "separators": SEPARATORS,
    "is_separator_regex": True,
    "chunk_size": 3_000,
    "chunk_overlap": 0,
}

# the generation is a digest of that dict — 12 hex chars is plenty
SLICER_GENERATION = hashlib.sha256(json.dumps(SLICER_CONFIG, sort_keys=True).encode()).hexdigest()[:12]
```

Then:

1. **Build the splitters *from* `SLICER_CONFIG`** — never from literals written a second time.
2. **Stamp every chunk** with `lit(SLICER_GENERATION)`.
3. **Name the append flow after the generation**, so a configuration change produces a *new* flow
   with a *fresh checkpoint* that appends a new generation beside the old rows instead of corrupting
   comparisons against them. (Same mechanism as keying an embedding flow on the model name — see
   [stateful-streaming-and-flows.md](./stateful-streaming-and-flows.md).)
4. **Filter to one generation in every consumer**, alongside the model filter.

```python
@dp.append_flow(target="document_slices", name=f"document_slices_{SLICER_GENERATION}")
def document_slices_flow(): ...
```

What makes it correct, and what it costs:

- **The digest is only an identity of the chunker if it covers every input the splitters take.**
  That is why `SLICER_CONFIG` is the single source both the splitter and the digest are built from,
  and why a test should assert its key set. An argument added to a splitter but not to the dict
  leaves the generation unchanged when it should have moved — the exact failure the pattern exists
  to prevent, arriving through the back door.
- **A chunker change re-chunks the whole corpus** rather than editing in place. That is correct and
  it is not free; the cost is proportional to the corpus and falls on whoever changes a separator.
- **Rows written before the stamp existed have no generation.** Adding the stamp late leaves a
  mixed table — a third of the table in the source project — so your consumers need an explicit
  policy for null generations (exclude them, or backfill). `[repo]`
- Retention is a real question: generations accumulate a full corpus copy each. Decide it when you
  adopt the pattern, not when storage complains.

## Measure chunking quality

You cannot tune a splitter you have not measured, and "the chunks look fine" does not survive a
corpus. The source project's evaluation query computes all of this; it is a good shopping list.

| Family | Metric | Reads as |
|---|---|---|
| **Corpus** | chunks, distinct documents, mean chunks/document | Scale, and whether fragmentation changed |
| **Size** | min / mean / p50 / p90 / p95 / p99 / max / stddev characters | p99 is what must fit the model window |
| **Size** | histogram, from tiny fragments to the `chunk_size` hard cut | A spike *at* the cut is the signal below |
| **Boundary** | `hard_cut_rate` — share of chunks at exactly `chunk_size` | High ⇒ the ladder never found a separator; boundaries are arbitrary |
| **Boundary** | `tiny_fragment_rate` — share under some floor (e.g. 50 chars) | High ⇒ a separator is ranked too high, or headings are being split off alone |
| **Boundary** | `mid_break_rate` — share not ending on a sentence terminator | The direct measure of "did we cut mid-sentence" |
| **Structure** | header coverage — share of chunks carrying a markdown heading | Low ⇒ header-first splitting is not actually happening |
| **Fragmentation** | chunks-per-document distribution + the most-fragmented documents | The tail is where the pathologies live |
| **Integrity** | reconstruction ratio — summed chunk characters vs source characters | <1 ⇒ content loss; >1 ⇒ duplication |
| **Integrity** | documents losing >10% or duplicating >5% | A short list you can actually open |
| **Eyeball** | the longest hard-cut chunks with their trailing 120 characters | The thirty seconds that explains the numbers |

Two habits around it:

- **`hard_cut_rate` and `mid_break_rate` are the two to watch.** They move in opposite directions to
  most "improvements" and will catch a separator reordering that the averages hide.
- **Run it as a before/after bakeoff on a fixed corpus**, with the thresholds written down *before*
  the run. The source project kept a separator-ladder bakeoff and a slicing-change evaluation
  alongside the pipeline for exactly this. Changing a ladder without a bakeoff is guessing.

## Don't

- Don't justify `chunk_size` by analogy to office software and call it decided.
- Don't rank a bare-number regex above `\n\n`.
- Don't disable structural separators for speed without recording the quality delta.
- Don't pick an embedding model before you know your p99 chunk size.
- Don't parse a chunk id for position without asserting the id format in a test.
- Don't add a splitter argument without adding it to the config dict the generation digests.
- Don't ship a chunking change without the before/after metrics.
