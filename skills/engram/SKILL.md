---
name: engram
description: "Use Engram, the user's local long-term memory, to recall past decisions, people and project history before answering, save lasting facts, correct what changed, and explain why a memory says what it says. Apply when the user asks what was decided or done before, states a decision, preference or lasting fact, says something has changed, or asks you to justify a conclusion that rests on saved memories."
---

# Engram

Engram is this user's long-term memory. It runs on their own computer, stores
text exactly as written, and finds it by meaning and exact words. It needs
no API key. Use it through the `engram_*` MCP tools (or `engram` on the
command line).

## Before you start

If no `engram_*` tools are available, tell the user and offer the setup:

```bash
pip install engram-chateau        # or: uv tool install engram-chateau
engram connect                    # lists the AI apps it can set up; then: engram connect <app>
```

For Claude Code, `engram install-hooks --apply` adds automatic recall on
every message, plus auto-save. Do not run setup commands without asking.

## Recall before answering

Call `engram_recall` with the user's message before answering anything that
may depend on earlier work, decisions, preferences, people or projects. It
returns only memories that clearly match, or says nothing matched.

- Do not recall for pure greenfield requests ("rename this variable").
- Use `engram_search` when you need more than the few memories recall gives.
- A result marked **OUTDATED** is history. Use the current version it points
  to, and say so if the difference matters.
- A result marked **DISPUTED** conflicts with another memory. Tell the user
  rather than choosing silently.

## Save what lasts

When the user makes a decision or states a lasting fact or preference, save
it with `engram_add_memory` (use the project's name as the wing). Say where
it came from with `source`: `user` (they said it), `primary` (an original
document, law, ruling, dataset), `secondary` (reporting or analysis), `tool`
(a search or program result) or `inference` (your own conclusion), plus
`source_ref` for a citation or URL.

## When something changes

Do not save a contradicting note. Call `engram_correct` with the old
memory's id and the new text, and the reason. The old one stays as history.
If `engram_add_memory` returns `possible_updates`, one of those may be what
you are replacing. If two memories conflict and it is unclear which is
right, use `engram_dispute`.

## Conclusions and evidence

When you save a conclusion, link it to what it rests on with `based_on`
(ids of the memories that are evidence) or `derived_from` (ids it was
inferred from). Save your own conclusions with `source: "inference"`.

Before relying on a saved conclusion, or when the user asks "why do you
think that?", call `engram_why` with its id. Report what it says:

- what it rests on, and whether that evidence was **corrected since**;
- which parts are recorded fact and which are inference;
- earlier versions and the evidence *they* rested on;
- anything under `concerns`, which needs review.

Never present an inference as a source. Quote a primary source's text and
say it is the source; keep official explanations and your own interpretation
separate from it. If nothing saved settles the question, say so.

`engram_check` lists everything that needs review (conclusions whose
evidence changed, inferences with no evidence, unresolved conflicts). It
changes nothing.

## Privacy

Memories are private. Do not paste them into other tools or send them
anywhere the user has not asked for.
