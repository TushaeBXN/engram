# Engram
<!-- mcp-name: io.github.TushaeBXN/engram -->
<img width="1024" height="558" alt="engram update image" src="https://github.com/user-attachments/assets/2afaa9df-0539-4837-94e7-e20b8840cc77" />

> **Your AI forgets everything when the chat ends. Engram helps it remember.**
> Free, private, runs on your own computer, and keeps every word exactly as you wrote it.

[![MIT License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Python 3.9+](https://img.shields.io/badge/python-3.9%2B-blue)](https://www.python.org/)
[![PyPI](https://img.shields.io/pypi/v/engram-chateau)](https://pypi.org/project/engram-chateau/)
[![CI](https://github.com/TushaeBXN/engram/actions/workflows/ci.yml/badge.svg)](https://github.com/TushaeBXN/engram/actions/workflows/ci.yml)

---

## The problem

On Monday you spend an hour with Claude working out why the login system leaks memory, and you decide to switch libraries. On Friday you open a new chat and ask *"why did we drop Passport again?"*

It has no idea. The conversation is gone, and so is the reasoning.

The same thing happens with everything you tell an AI: your sister's birthday, the bug you already fixed, the reason a setting is the way it is. Every new chat starts from zero.

**Engram is a memory that outlasts the chat.** It saves your notes, files and conversations, and when you ask a question later, it finds the right one, even if you phrase it completely differently.

---

## See it work

Two ordinary notes go in:

```text
notes/decisions.md   We switched from Passport to Lucia on March 3 because
                     Passport sessions kept leaking memory under load.
notes/personal.md    My sister Maya's birthday is June 14. She loves anything
                     with sunflowers.
```

```bash
engram mine notes --wing life
```

Days later, ask in your own words. None of these questions share a sentence with the notes:

```text
$ engram search "why did we change the auth library"
  1   life/notes   We switched from Passport to Lucia on March 3 because
                   Passport sessions kept leaking memory under load.

$ engram search "gift idea for Maya"
  1   life/notes   My sister Maya's birthday is June 14. She loves anything
                   with sunflowers.
```

Hook it up to Claude and it does this by itself: Claude looks things up in Engram when it needs them, and Engram saves your Claude Code sessions automatically.

---

## Try it in 2 minutes

You need **Python 3.9 or newer** (3.11 to 3.14 is best). Check with `python3 --version`.

**1. Install**

```bash
pip install engram-chateau
```

> On PyPI the package is called `engram-chateau`, but the command you type is just `engram`. (A different, unrelated package already owns the name `engram`.)

**2. Give it something to remember**

```bash
engram mine ~/Documents/notes --wing notes      # any folder of notes, docs or code
```

The first run downloads a small language model (about 80 MB) that lets Engram understand meaning. After that, everything works offline.

**3. Ask it something**

```bash
engram search "what did I decide about the database"
```

That's all you need to try it.

### Connect it to your AI app

Engram works with any app that speaks **MCP**, the standard way AI apps plug in tools. One command adds it:

```bash
engram connect cursor        # or: claude-desktop, windsurf, vscode, gemini, codex, zed, lm-studio
engram connect all           # every supported app on this computer
engram connect               # list them, with ✓ next to the ones you have
```

It adds Engram to that app's settings (keeping everything else, with a `.bak` backup) and tells you how to restart the app. Run it again any time; it changes nothing the second time.

| App | Setting it writes |
|---|---|
| Claude Desktop | `claude_desktop_config.json` |
| Cursor | `~/.cursor/mcp.json` |
| Windsurf | `~/.codeium/windsurf/mcp_config.json` |
| VS Code (Copilot agent mode) | your user `mcp.json` |
| Gemini CLI | `~/.gemini/settings.json` |
| Codex CLI | `~/.codex/config.toml` |
| Zed, LM Studio | prints the snippet to paste |

Every app then has 31 `engram_*` tools: recall, search, remember, correct an outdated memory, link a conclusion to its evidence, explain why a memory says what it says, a topic's history, a knowledge graph of people and facts, and more. On connect, Engram also tells the AI how to use them: check memory before answering anything that depends on past work, save decisions, and correct rather than contradict. (Apps decide whether to pass that guidance to the model; most current ones do.) Ask *"remember that we use tabs in this repo"*, *"what did we decide about auth?"* or *"we moved to PostgreSQL, update that"*.

**Claude Code** gets the most: memory that works without being asked.

```bash
engram connect claude-code        # prints the one-line `claude mcp add` command
engram install-hooks --apply      # then restart Claude Code
```

`install-hooks` adds three Claude Code hooks to `~/.claude/settings.json` (your existing settings are kept, with a backup):

- **Auto-recall.** Each time you send Claude a message, Engram searches your memory first. If something clearly relevant turns up, Claude gets a short note with up to 3 memories before it answers, current versions first (with what they replaced and why) and outdated ones labelled. You ask *"why did we drop Passport?"* in a brand-new chat, and Claude already knows. Nothing is added when nothing is relevant, a memory isn't repeated within a session, and it takes about a second once warm (the first message after your computer starts it can take several seconds while it loads).
- **Project-aware.** Memories are filed under the project you're working in (the git repo or folder name), and recall shows that project's memories first; other projects' notes only appear when they match very closely.
- **Auto-save.** Every file Claude edits is saved.
- **Save before compacting.** The conversation is saved before Claude Code compacts it.

Preview what auto-recall would hand Claude with `engram recall "your message"`. Run `engram install-hooks` without `--apply` to see the settings instead of applying them, or add `--no-recall` to skip auto-recall.

**Any other MCP app:** point it at the command `engram-mcp` (or `python -m engram.mcp_server`). Engram is also listed in the official [MCP registry](https://registry.modelcontextprotocol.io) as `io.github.TushaeBXN/engram`.

**Apps that don't speak MCP** (Open WebUI, n8n, your own scripts) can use Engram over a small local web API:

```bash
engram serve                  # http://127.0.0.1:7742, the same tools and rules as MCP
```

Point the app at `http://127.0.0.1:7742/openapi.json`; every tool is described there. Or call it directly:

```bash
curl -s localhost:7742/v1/tools/engram_recall -H 'Content-Type: application/json' \
     -d '{"message": "why did we drop Passport?"}'
```

Memories are private, so it is strict by default. It listens on localhost only, and refuses requests that look like they come from a web page or through a proxy. To reach it from another machine, use `engram serve --host 0.0.0.0`: that always requires a token (created on first use in `~/.engram/server/token`, never printed), sent as `Authorization: Bearer <token>`. `engram serve --token` requires one even on localhost. No CORS headers are ever sent, so a web page can't talk to it.

**Teach any coding agent to use it.** [`skills/engram/SKILL.md`](skills/engram/SKILL.md) is a ready-made agent skill: when to recall, save and correct, and how to explain a conclusion. Install it with `npx skills add TushaeBXN/engram` (or copy the file).

<details>
<summary><b>Prefer uv, pipx or a guided setup?</b></summary>

```bash
uv tool install engram-chateau     # or: pipx install engram-chateau
engram init ~/myproject            # guided setup: your AI's identity, a default wing, then saves the project
```

Both put `engram` and `engram-mcp` on your PATH without touching your system Python.
</details>

---

## Who it's for

**🧑‍💻 Developers using Claude Code.** Engram quietly saves the files Claude touches and the conversations behind them. Months later, *"why is the retry limit 7?"* brings back the actual discussion, not a guess.

**🤖 People building an AI companion or agent.** Give your bot a memory of its own: what it has learned about you, a diary, and a knowledge graph of people and facts (*"Kai works on Orion, since June"*). It all runs offline in a few lines of Python. Engram started life as exactly this, the memory of a personal companion app.

**📚 Writers, researchers and note-takers.** Point it at a folder of notes, an Obsidian vault, or Notion or Linear exports, and search across all of it by meaning: *"that idea I had about pricing tiers"*.

---

## Why Engram is different

- **🔒 It's yours.** Everything lives in one folder on your computer (`~/.engram/`). No account, no cloud, no API key, no tracking.
- **📝 It keeps your words.** Most AI memory tools have an LLM rewrite your conversations into short "facts" and throw the original away. Engram stores the original text and finds it again. Nothing gets lost in a summary.
- **🧠 It understands what you mean.** It finds *"we switched from Passport to Lucia"* when you ask about *"changing the auth library"*. It also matches exact names and numbers (`INV-20931`), and understands time: *"two weeks ago"*, *"in June"*, *"on May 8"*.
- **💸 It's free to run.** It needs no LLM to save or search, so there are no per-message costs and nothing to rate-limit.
- **🎯 It's accurate.** On the two standard tests of AI memory, it beats the best published no-LLM results ([numbers below](#how-good-is-it)).
- **📖 You can read all of it.** About 10,000 lines of plain Python, MIT licensed. If you want to know exactly what happens to your data, you can.
- **🔄 It knows when it's out of date.** When a decision changes, the new memory is marked as replacing the old one. Search gives you the current answer first, and the old one stays below it as history, with when and why it changed.
- **🔑 It can hide secrets for you.** Turn on `redact_secrets` and API keys, tokens and passwords are blanked out before anything is written to disk.

---

## How it works

Engram files memories the way you'd organise a big house: one **wing** per person or project, a **room** per topic, a **hall** per kind of memory, and inside, **drawers** holding the original text.

```
Wing   – a person or project        ("myapp", "life")
└── Room  – a topic                 ("auth-migration")
    └── Hall – the kind of memory   (facts, events, discoveries, preferences, advice)
        └── Drawer – your original text, word for word
```

You don't have to manage any of this; Engram sorts things as it saves them. When you search, it weighs several clues together:

| Clue | What it does |
|---|---|
| **Meaning** | Finds text that means the same thing, even in different words |
| **Exact words** | A full-text index catches names, numbers and rare words the meaning search misses |
| **Time** | *"What did I buy two weeks ago?"* or *"what happened in June?"* favours memories from then |
| **Passing remarks** | Notices things you mentioned in passing (*"I've been sleeping badly"*) so later questions find them |
| **Recency** | Leans slightly toward newer memories; pinned ones never fade |
| **Reranker** *(optional)* | A small local model re-reads the top 20 and puts the best one first |

At the start of a session, Engram can also hand the AI a small "wake-up" note (who it is plus key facts: pinned ones first, then the newest, about 120 tokens by default), so it never starts completely cold.

---

## When things change

In March you note that the app stores everything in SQLite. In April you move to PostgreSQL. Most memory tools now hold two contradicting notes and return whichever matches the question best.

In Engram, you (or Claude, or your agent) record the change once:

```bash
engram correct file-05aa607a "We migrated the app from SQLite to PostgreSQL on April 9" --reason "SQLite locked under concurrent writes"
```

From then on, search puts the current answer first and keeps the old one, clearly labelled, right below it:

```text
$ engram search "which database does the app use"
  1  c6e0b7b4       [current, replaces file-05aa607a] We migrated the app from SQLite to PostgreSQL on April 9…
  2  file-05aa607a  [outdated → c6e0b7b4] Decision: the app stores everything in SQLite because…
```

`engram history file-05aa607a` shows the whole story: what it said, what replaced it, when, and why. Nothing is ever silently deleted. Old evidence stays searchable, and a mistaken correction can be undone with `engram supersede <id> --undo`.

Engram never decides by itself that one note contradicts another. Deciding what is true is the job of whoever is using it. When Claude saves a memory, Engram points out existing memories it might update, and Claude decides.

### Why does it say that?

A memory can say what it rests on and where it came from, so a conclusion never floats free of its evidence:

```bash
engram source 903294e5 primary --ref "U.S. Const. art. I, § 2"   # where a memory came from
engram link c9422f65 based_on 903294e5 --reason "constitutional text"
engram link c9422f65 derived_from 2da14213                       # also: contradicts, supersedes
```

Sources are `user` (you said it), `primary` (an original document, law, ruling or dataset), `secondary` (reporting or analysis), `tool` (a search or program result) and `inference` (an AI's own conclusion). Inferences stay labelled as inferences.

`engram why <id>` explains any memory: its source and date, whether it is a record or an inference, the evidence behind it, whether that evidence has since been corrected or disputed, earlier versions and *their* evidence, and, with `--query`, why search ranked it:

```text
$ engram why c9422f65
c9422f65-…  amy/views  2026-10-20
  My view: population apportionment is the baseline; the 2025 map changes the state's representation.
  Source: AI inference.  Type: an inference.

Evidence
  based_on 903294e5  2026-10-20  primary source, U.S. Const. art. I, § 2
    Article I, Section 2: Representatives shall be apportioned among the several States…
  derived_from 2da14213  2026-10-20  secondary source  OUTDATED → 914e0cb2
    Report: the legislature adopted a new map in 2025.

Needs review
  • evidence 2da14213 was corrected (current version: 914e0cb2); check whether this still holds
```

`engram check` lists everything like that across your memory: conclusions whose evidence was corrected or disputed, inferences with no evidence, conflicts nobody has settled, links to deleted memories. It changes nothing. When a position is revised, the old one keeps the evidence it had, so you can always see what the earlier view rested on and what supports the new one.

**Backups.** `engram export backup.json.gz` puts every memory, correction, knowledge-graph fact and diary into one file. `engram import backup.json.gz` restores it on another computer, after checking the whole file first: if anything is wrong, nothing is changed. The format is documented in [docs/backup-format.md](docs/backup-format.md).

---

## How good is it?

Researchers test AI memory with two public benchmarks. Each gives the system long chat histories and asks questions whose answers are buried somewhere inside. The score is how often the system finds the right conversation.

| Benchmark (default settings, no LLM) | Engram |
|---|---|
| **[LongMemEval](https://github.com/xiaowu0162/LongMemEval)**: 500 questions, right conversation in the top 5 | **98.8%** |
| **[LoCoMo](https://github.com/snap-research/locomo)**: 1,986 questions, answer's sessions in the top 10 | **92.1%** |

In plain terms: ask Engram 500 questions about months of chat history, and for 494 of them the right conversation is in its top 5 results. It gets there with a small model that runs on a laptop, no LLM and no API. These tests measure finding the right conversation. They don't measure whether corrections, evidence links or recall notes make an AI more accurate; [benchmarks/trust_eval.py](benchmarks/trust_eval.py) checks those, and the results are listed below.

**Does it keep memory trustworthy?** Those tests don't cover corrections, the notes handed to a model, or crashes, so [`benchmarks/trust_eval.py`](benchmarks/TRUST.md) checks them. On its own (author-written, deliberately small) scenarios, in the current version:

| | Result |
|---|---|
| After a fact changes, the current version comes first | 20 of 20 questions (4 of 20 with no correction history) |
| Auto-recall note size vs. pasting every memory | 92 tokens vs. 5,134 |
| Auto-recall note contains the answer | 17 of 20 (a plain top-5 search: 19 of 20) |
| Auto-recall speaks up when nothing relevant is stored | 0 of 20 times |
| Memory files left half-written after 40 forced crashes | 0 (10 before 1.10.1 fixed this) |
| Corrections or links lost with 6 writers in parallel | 0 of 240 |

Auto-recall trades some answers for silence and small notes; [the full table](benchmarks/TRUST.md), what it doesn't show, and how to run it yourself are there. Nothing here shows that it makes an AI more accurate end to end; that hasn't been tested.

<details>
<summary><b>The fine print</b></summary>

- It uses a small local embedding model (all-MiniLM-L6-v2). Engram indexes the assistant's replies as well as yours.
- **These numbers are not held-out.** Engram's boosts are fixed general rules, not tuned per question, but we chose which ones to ship by watching LongMemEval and LoCoMo scores from version to version (each step is in [BENCHMARKS.md](benchmarks/BENCHMARKS.md)), so some of the score is fitted to these two tests.
- **Raw meaning search alone, with none of those boosts, scores 96.8% R@5 on LongMemEval.** The boosts add about two points.
- One LongMemEval question is worth 0.2 points, so small differences are a question or two.
- An LLM reranker (which needs an API key) can raise scores further. Engram doesn't offer one, by design.
- Everything is reproducible from this repo. Full per-question-type results, earlier versions and the exact commands are in [benchmarks/BENCHMARKS.md](benchmarks/BENCHMARKS.md).
</details>

---

## Should you use Engram?

There are several good memory tools. Here's an honest guide.

| If you want… | Use |
|---|---|
| Memory for **Claude Code or Claude Desktop** that's private, free and just works | **Engram** |
| A memory **library for your own AI app, companion or agent**, offline with no per-call costs | **Engram** |
| To **read and trust** every line of code that touches your data | **Engram** |
| Memory for a **multi-user product** in the cloud, with a dashboard and an API | A hosted service such as Mem0, Zep or Supermemory (usually needs an account, an API key and an LLM) |
| Just a few standing rules (*"use tabs"*, *"my name is…"*) | Claude's built-in memory or a `CLAUDE.md` file |

---

## Use it in your own app

```python
from engram.agents import AgentDiary
from engram.backends import get_backend
from engram.chateau import Chateau
from engram.knowledge_graph import KnowledgeGraph
from engram.searcher import Searcher

memory = Chateau()                                   # your memory folder (~/.engram/chateau)
searcher = Searcher(get_backend("chromadb"), memory)

for hit in searcher.search("what music does Maya like", n=5):
    print(hit["text"], hit["final_score"])

AgentDiary("my-assistant").write("Helped plan the week")               # an agent's diary
KnowledgeGraph().add(subject="Maya", predicate="likes", obj="jazz")    # facts about people and things
```

These calls are pinned by `tests/test_public_api.py`, so apps built on them keep working across releases. For the full default search (exact-word index included), build the backend with `engram.backends.backend_from_config(engram.config.load_config())`.

---

## Everyday commands

```bash
# Save things
engram mine ~/project --wing myapp                 # a folder of files
engram mine ~/Downloads/claude-export --mode convos --wing myapp   # a Claude, ChatGPT or Slack export
engram watch ~/project --wing myapp                # keep saving as files change

# Find things
engram search "auth decisions" --wing myapp
engram answer "What did we decide about the database?"   # a written answer (needs Ollama)
engram replay --room auth-migration                # a topic's history, in order

# Fix and keep things
engram correct <id> "the new, correct version"     # replace an outdated memory (old one kept as history)
engram history <id>                                # what replaced what, when and why
engram why <id>                                    # where it came from, what it rests on, what changed
engram forget <id>                                # delete a memory for good (shows what changes; add --yes)
engram export backup.json.gz                       # back up everything to one file
engram import backup.json.gz                       # restore it (checked first; safe to repeat)

# Look after it
engram status                                      # what's in your memory
engram wake-up                                     # the short start-of-session note
engram audit --fix                                 # health check and safe fixes
```

The ID is the short code in the first column of `engram search` results.

<details>
<summary><b>Full command reference</b></summary>

### Setup
```bash
engram init <dir>                              # guided setup
engram serve [--host H] [--port P] [--token]  # local web API for apps without MCP (OpenAPI at /openapi.json)
engram reindex [--wing W]                      # rebuild the search index (after changing the embedding model)
engram connect <app>                           # add Engram to Cursor, VS Code, Gemini CLI, Codex… (no app: list)
engram install-hooks --apply                   # Claude Code hooks: auto-recall, auto-save, save before compacting
engram recall "a message"                      # preview what auto-recall would give Claude
engram setup-reranker                          # download the reranker model (90 MB) and turn it on
engram setup-reranker --disable                # turn the reranker off
```

### Saving
```bash
engram mine <dir>                              # project files
engram mine <dir> --mode convos                # conversation exports (Claude, ChatGPT, Slack, Claude Code)
engram mine <dir> --wing myapp --room auth     # choose the wing and room
engram mine <dir> --since 2026-01-01           # skip older files
engram mine <dir> --plugin obsidian            # also: notion, linear
engram watch <dir> --wing myapp                # auto-save on change
engram split <dir> [--dry-run]                 # split concatenated transcripts
engram remember-type "Prefer SQLite for local dev" preference --wing myapp
engram remember-type --list                    # the 13 memory types
```

### Searching
```bash
engram search "query" [--wing W] [--room R] [--results 20]
engram search "query" --no-decay               # ignore recency
engram search "query" --no-hybrid              # meaning only
engram search "query" --rerank / --no-rerank   # force the reranker on or off for one search
engram answer "question" [--wing W] [--model llama3.2] [--chunks 8]
```

### Context, history and graph
```bash
engram wake-up [--wing W] [--rebuild]
engram replay --room R [--wing W] [--type decision] [--since 2026-06-01] [--min-confidence 0.8]
engram kg query "Kai" [--all]
engram kg add "Kai" works_on "Orion" --from 2025-06-01
engram kg invalidate "Kai" works_on "Orion" --ended 2026-03-01
engram kg timeline "auth-migration"
engram graph [--wing W] [--output file.png]   # needs: pip install "engram-chateau[viz]"
```

### Corrections
```bash
engram correct <id> "new text" [--reason "why"]  # save a correction that replaces <id>
engram supersede <old-id> <new-id> [--reason R]  # mark an existing memory as replacing another
engram supersede <old-id> --undo                 # make <old-id> current again
engram history <id>                              # status and full replacement history
engram correct <id> "text" --source primary --ref "cite" --based-on <evidence-id>
```

### Deleting
```bash
engram forget <id>                                     # show what deleting it would change
engram forget <id> --yes                               # delete it, its search entries and every link to it
```
Forgetting is for things that should never have been saved. A memory it replaced becomes current again, memories that rested on it lose that evidence (`engram check` lists any left with nothing behind them), and earlier exports still contain it. To change a memory without losing its history, use `engram correct` instead.

### Evidence and explanations
```bash
engram link <id> based_on <evidence-id> [--reason R]   # <evidence-id> supports <id>
engram link <id> derived_from <other-id>               # <id> was inferred from <other-id>
engram link <id> contradicts <other-id>                # conflict, undecided
engram link <id> supersedes <old-id>                   # <id> replaces <old-id>
engram link <id> based_on <evidence-id> --undo         # remove a link
engram source <id> user|primary|secondary|tool|inference [--ref "citation or URL"]
engram why <id> [--query "the question"] [--json]      # explain a memory
engram check [--json]                                  # what needs review; changes nothing
```

### Backups
```bash
engram export <file>[.gz]                        # back up everything to one file
engram import <file> [--dry-run] [--overwrite]   # restore; the whole file is checked first
```

### Maintenance
```bash
engram status
engram audit [--fix]
engram conflicts                               # resolve contradicting knowledge-graph facts
engram compress [--wing W] [--room R]          # rebuild short summaries (ES)
engram provenance <drawer-id> [--history]
engram provenance --summary
engram ui                                      # local notes app at http://127.0.0.1:7741
```
</details>

---

## Settings

Everything works out of the box. If you want to tweak things, settings live in `~/.engram/config.json`. Every key is optional, and the defaults are the benchmarked setup.

| Setting | Default | What it does |
|---|---|---|
| `redact_secrets` | `false` | Blank out API keys, tokens and passwords (`[REDACTED:…]`) before anything is saved |
| `reranker` | `false` | Local reranker; turn on with `engram setup-reranker`. While off, nothing extra is downloaded |
| `recall` | `true` | Auto-recall in Claude Code (needs `engram install-hooks`); `false` turns it off |
| `recall_max` / `recall_min_relevance` | `3` / `0.30` | At most this many memories per message, and how closely they must match (0 to 1) |
| `recall_preference_min_relevance` | `0.20` | The same bar for saved preferences, lower because a request for a choice rarely repeats the preference's words |
| `recall_exclude_wings` | `["library"]` | Wings auto-recall never shows |
| `recall_other_min_relevance` | `0.55` | How closely another project's memories must match to be shown |
| `projects` | `{}` | Map folders to wings when the folder name isn't what you want, e.g. `{"~/code/app": "billing"}` |
| `keyword_search` | `true` | Exact-word index searched alongside meaning (SQLite, no download), built from your existing memories the first time it runs |
| `embedding_api_url` / `embedding_api_model` | unset | Use an embedding server you run (LM Studio, Ollama, llama.cpp, vLLM: anything with `/v1/embeddings`) instead of the built-in English model, e.g. for other languages. Run `engram reindex` once after setting it. The server must be on this computer or your network unless `embedding_api_allow_remote` is `true`, because your memories' text is sent to it |
| `vector_backend` | `chromadb` | Search engine: `chromadb`, `faiss` or `sqlitevec` (no compiled parts) |
| `hybrid_weight` | `0.3` | Boost for results sharing your exact words; `0` turns it off |
| `temporal_weight` | `0.4` | Boost for memories near a time the question names; `0` turns it off |
| `preference_summaries` | `true` | Index a short summary of preferences and concerns mentioned in passing |
| `l1_budget_tokens` | `120` | Size of the key-facts part of the wake-up note |
| `rerank_top` | `20` | How many top results the reranker reorders |
| `decay_factor` / `decay_max_days` | `0.005` / `90` | How much newer memories are favoured, and for how long |
| `chateau_path` | `~/.engram/chateau` | Where memories are stored |

`ENGRAM_VECTOR_BACKEND=sqlitevec engram …` switches the backend for one run. An embedding server works with the default `chromadb` backend; each server and model keeps its own index, so switching back needs no reindex and your memories are never changed. `~/.engram/identity.txt` holds the short identity that starts each wake-up note.

---

## Troubleshooting

- **`engram: command not found` after installing.** pip put it somewhere not on your PATH. Use `python3 -m pip install --user engram-chateau`, or install with `uv tool install engram-chateau` / `pipx install engram-chateau`, which handle PATH for you.
- **`pip: command not found`.** Try `pip3` or `python3 -m pip`. Inside a `uv` virtual environment, use `uv pip install …`.
- **Moving to a new computer.** Run `engram export backup.json.gz` on the old one, install Engram on the new one, then `engram import backup.json.gz`. Search indexes are rebuilt during the import.
- **Claude doesn't show the engram tools.** Restart Claude Code or Claude Desktop after adding the server. If the app can't find `engram-mcp`, give it the full path from `which engram-mcp`.
- **"ChromaDB failed to load".** ChromaDB's compiled parts don't match your Python. Try `pip install --force-reinstall --no-cache-dir chromadb`, or set `"vector_backend": "sqlitevec"`, which needs no compiled parts. Then run `engram mine` again, because each backend keeps its own index.
- **Python 3.15 or newer.** ChromaDB can't install there yet, so Engram falls back to `sqlitevec`, which matches words rather than meaning. For meaning-based search, use Python 3.11 to 3.14.
- **"No such command" after updating from GitHub.** Run `git pull origin main`, then `pip install -e .` (or `uv pip install -e .`) in your Engram folder.
- **The search Relevance column shows `<0.001`.** The reranker found nothing that really answers that question; try a more specific one.

---

<details>
<summary><b>Under the hood: shorthand, memory layers, web UI, code map</b></summary>

### Engram Shorthand (ES)

A compact text form any LLM can read without a decoder. It's used only for the short context Engram loads into a model; your drawers always keep the original text. ES drops filler words, saving about 1.6× on prose and 1.1× on code.

```python
from engram.shorthand import compress
compress("The authentication module is a critical component that has a dependency on the database.")
# → "auth module=★★ component +dep on db."
```

### Memory layers

| Layer | Content | Size | Loaded |
|---|---|---|---|
| L0 | Identity: who the AI is | ~50 tokens | Always |
| L1 | Key facts, in shorthand | up to 120 tokens (`l1_budget_tokens`) | Always |
| L2 | The current topic's memories | On demand | When the topic comes up |
| L3 | Full search | On demand | When asked |

### Web UI

`engram ui` opens a local notes app at http://127.0.0.1:7741, with a graph of linked notes, tags, pinned notes, a daily journal and Markdown editing. It keeps its notes in your browser for now, and doesn't yet show the memories in `~/.engram/`; use `engram search` or the MCP tools for those.

<img width="1126" height="932" alt="Engram notes UI with knowledge graph" src="https://github.com/user-attachments/assets/870d76e7-bdc3-42a5-9056-6a54a1dd7ef1" />

### Code map

| File | What it does |
|---|---|
| `engram/chateau.py` | Wings, rooms, halls and drawers on disk |
| `engram/searcher.py` | Search: meaning, keywords, time, recency, reranking |
| `engram/keyword_index.py` | Exact-word index (SQLite FTS5) merged with meaning search |
| `engram/indexing.py` | Splits long text into chunks for the index |
| `engram/temporal.py` | Understands "two weeks ago", "in June", "on May 8" |
| `engram/preferences.py` | Spots preferences and concerns in messages |
| `engram/redact.py` | Optional secret redaction |
| `engram/reranker.py` | Optional local reranker (ONNX) |
| `engram/miner.py`, `engram/convo_miner.py` | Saving files and conversations |
| `engram/lineage.py` | Corrections: which memories are current, which were replaced, and why |
| `engram/relations.py` | Evidence links, sources, `engram why` and `engram check` |
| `engram/server.py` | `engram serve`: the local web API and its request checks |
| `engram/validate.py` | Checks tool arguments against each tool's schema (MCP and web) |
| `engram/embedding.py` | Optional embedding server instead of the built-in model |
| `engram/backup.py` | `engram export` / `engram import` |
| `engram/recall.py` | Auto-recall hook for Claude Code |
| `engram/mcp_server.py` | MCP server (31 tools), run as `engram-mcp` |
| `engram/connect.py` | `engram connect`: adds Engram to AI apps' settings |
| `engram/layers.py`, `engram/shorthand.py` | Wake-up note and ES shorthand |
| `engram/knowledge_graph.py`, `engram/agents.py` | Knowledge graph and agent diaries |
| `engram/backends/` | ChromaDB (default), FAISS, sqlite-vec |
| `engram/plugins/` | Obsidian, Notion, Linear importers |
| `engram/hooks/` | Claude Code save and pre-compact hooks |
| `benchmarks/` | LongMemEval and LoCoMo runners |
</details>

---

## Requirements

- **Python 3.9 or newer.** 3.11 to 3.14 is recommended for meaning-based search.
- **Installed automatically:** ChromaDB, typer, rich, watchdog, questionary, pyyaml and requests.
- **Optional extras:** `engram-chateau[faiss]`, `[sqlitevec]`, `[viz]` (graph pictures) or `[all]`.
- **Optional:** [Ollama](https://ollama.com) for `engram answer`.

**Internet use:** none, apart from two one-time downloads. The embedding model (about 80 MB) downloads the first time you save or search. The optional reranker (90 MB) downloads only if you run `engram setup-reranker`. Your memories never leave your machine.

---

## Contributing

Bug reports, ideas and pull requests are welcome.

```bash
git clone https://github.com/TushaeBXN/engram && cd engram
pip install -e ".[dev]"
pytest
```

<details>
<summary><b>Releasing (maintainers)</b></summary>

Engram is published to PyPI as `engram-chateau` from `.github/workflows/publish.yml`, using PyPI trusted publishing (no stored token; owner `TushaeBXN`, repository `engram`, workflow `publish.yml`, environment `pypi`).

1. Bump `version` in `pyproject.toml` and `__version__` in `engram/__init__.py`, and add a `CHANGELOG.md` entry.
2. Merge to `main`.
3. Create a **new** GitHub release *after* the merge, tagged `v<version>` with the dots kept (for example `v1.5.1`, not `v1.51`), targeting `main`. The workflow checks the tag matches the version, runs the tests, builds and uploads.
</details>

---

## Credits and license

Engram's design (wings, rooms, halls, drawers and a temporal knowledge graph) is inspired by other open-source memory systems. Some retrieval ideas (the exact-word index and date understanding) are adapted from [Hindsight](https://github.com/vectorize-io/hindsight).

MIT © 2026 Tushae Thomas

If Engram helps you remember something that mattered, a ⭐ helps other people find it.
