---
name: write-technical
description: 'Use when you write or communicate in English — chat replies, documentation, READMEs, commit messages, pull request text, code comments. Once this skill is active, apply it to every response for the rest of the session, not only the task that triggered it. Applies ASD-STE100 Simplified Technical English: short sentences (20 words for an instruction, 25 for a description), active voice, the imperative for steps, one meaning for each word, consistent terms, plain words, no idioms. Covers the public writing rules, not the proprietary approved-word dictionary.'
applyTo: '**'
---

# Writing in Simplified Technical English

> **What this is.** A controlled-English style for technical writing, based on ASD-STE100 Simplified
> Technical English. It makes prose short, direct and unambiguous, so a coding agent and a
> non-native reader both read it the same way. It covers the public **writing rules** only. The STE
> **dictionary** of approved words is proprietary, so it is not reproduced here — select the
> simplest correct word instead. It governs prose, not code identifiers or the content of data.

> **Scope once active.** When you load this skill, apply it to every response for the rest of the
> session, not only the task that triggered it. It governs all the English you write, including
> short chat replies and summaries.

## The rules that prevent most ambiguity

- Write short sentences. Use 20 words or fewer for an instruction. Use 25 words or fewer for a
  description.
- Write one instruction in one sentence. Put each step in its own sentence.
- Use the active voice. Do not use the passive voice.
- Use the imperative for an instruction. For example, write "Open the file".
- Prefer the present tense. Do not use an "-ing" form unless it is a technical name.
- Keep one meaning for each word, and one word for each meaning. Do not use a synonym for variety.
- Use the same term for the same thing every time. Do not switch between "folder" and "directory".
- Use plain, common words. Do not use jargon, idioms, slang or metaphor.
- Keep articles such as "a", "an" and "the". Do not drop words to make the text shorter.
- Do not make a noun group of more than three words.
- Keep paragraphs short. Use six sentences or fewer.
- Use a vertical list for complex or sequential information.
- Start a warning or a caution with the command, then give the reason.

## Quick symptom → fix index

| Symptom | Fix |
| --- | --- |
| A sentence runs past ~20 words | Split it. Keep one idea in one sentence. |
| "is handled by", "was processed" | Rewrite in the active voice with a clear actor. |
| The same thing has two names | Choose one term and use it everywhere. |
| A noun stack like "data access layer config" | Break it up with prepositions, or rename it. |
| An idiom such as "ping me" or "low-hanging fruit" | Replace it with a literal phrase. |

## Upstream documentation (sources)

- ASD-STE100 Simplified Technical English — the specification and its writing rules:
  https://www.asd-ste100.org/

## When to use this skill

Use it for documentation, READMEs, commit messages, pull request text, review comments, and chat
replies — any English that a person or an agent must read and act on. Do not apply it to code
identifiers, string literals, or the content of data.

## Related skills

- [document-decisions](../document-decisions/SKILL.md) — records *why* a value was chosen; this
  skill governs how to write that record clearly.
