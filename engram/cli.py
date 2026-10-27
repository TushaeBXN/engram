"""Engram CLI — full command surface via Typer + Rich.

All commands follow the spec in BRIEF.md.  Every subcommand that writes
to the terminal uses Rich for tables, panels, and progress bars.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from engram.config import get_chateau_path, load_config
from engram.lineage import short_id

app = typer.Typer(
    name="engram",
    help="Local, private long-term memory for AI.",
    add_completion=True,
    rich_markup_mode="rich",
)
console = Console()


# ---------------------------------------------------------------------------
# Lazy initialisation helpers
# ---------------------------------------------------------------------------

def _palace():
    from engram.chateau import Chateau
    return Chateau()


def _backend(cfg=None):
    from engram.backends import BackendUnavailableError, backend_from_config
    c = cfg or load_config()
    from engram.embedding import EmbeddingConfigError
    try:
        return backend_from_config(c)
    except (BackendUnavailableError, EmbeddingConfigError) as exc:
        console.print(str(exc), style="red", markup=False)
        raise typer.Exit(1)


def _searcher(palace=None, backend=None, cfg=None):
    from engram.searcher import Searcher
    c = cfg or load_config()
    p = palace or _palace()
    b = backend or _backend(c)
    return Searcher(b, p, c)


def _kg():
    from engram.knowledge_graph import KnowledgeGraph
    return KnowledgeGraph()


# ---------------------------------------------------------------------------
# engram init
# ---------------------------------------------------------------------------

@app.command("init")
def cmd_init(
    directory: Optional[str] = typer.Argument(None, help="Project directory to mine after init."),
):
    """Guided onboarding — set up your memory château."""
    from engram.onboarding import Onboarder
    Onboarder().run(directory)


# ---------------------------------------------------------------------------
# engram mine
# ---------------------------------------------------------------------------

@app.command("mine")
def cmd_mine(
    directory: str = typer.Argument(..., help="Directory or file to mine."),
    wing: str = typer.Option("default", "--wing", "-w", help="Wing to assign memories to."),
    mode: str = typer.Option("files", "--mode", "-m", help="'files' or 'convos'."),
    room: Optional[str] = typer.Option(None, "--room", "-r", help="Room to assign memories to."),
    since: Optional[str] = typer.Option(None, "--since", help="Skip files older than ISO date."),
    plugin: Optional[str] = typer.Option(None, "--plugin", "-p", help="Plugin: obsidian | notion | linear"),
):
    """Mine a directory into the château."""
    cfg = load_config()
    palace = _palace()
    backend = _backend(cfg)

    if plugin:
        from engram.miner import Miner
        from engram.plugins import get_plugin
        plug = get_plugin(plugin)
        with console.status(f"Fetching from [cyan]{directory}[/cyan] via [bold]{plugin}[/bold]..."):
            docs = plug.fetch(directory)
        miner = Miner(palace, backend, cfg)
        drawers = []
        for doc in docs:
            from engram.chateau import Drawer
            from engram.indexing import index_drawer
            d = Drawer(
                content=doc["content"],
                wing=wing,
                room=Path(doc["metadata"].get("path", "unknown")).stem,
                hall="facts",
                timestamp=doc["timestamp"] or "",
                tags=["plugin", plugin],
            )
            palace.save_drawer(d)
            index_drawer(backend, d.id, d.content, {
                "wing": wing, "room": d.room, "hall": d.hall,
                "timestamp": d.timestamp, "source": plugin,
            })
            drawers.append(d)
        _mine_success(drawers, directory)
        return

    from engram.miner import Miner
    miner = Miner(palace, backend, cfg)

    with console.status(f"Mining [cyan]{directory}[/cyan]..."):
        try:
            drawers = miner.mine(directory, wing=wing, room=room, mode=mode, since=since)
        except FileNotFoundError as e:
            console.print(f"[red]Error:[/red] {e}")
            raise typer.Exit(1)

    _mine_success(drawers, directory)


def _mine_success(drawers, directory):
    console.print(
        Panel(
            f"Mined [bold]{len(drawers)}[/bold] drawer(s) from [cyan]{directory}[/cyan]",
            title="[green]✓ Mine complete[/green]",
            border_style="green",
        )
    )


# ---------------------------------------------------------------------------
# engram watch
# ---------------------------------------------------------------------------

@app.command("watch")
def cmd_watch(
    directory: str = typer.Argument(..., help="Directory to watch."),
    wing: str = typer.Option("default", "--wing", "-w", help="Wing to assign memories to."),
    mode: str = typer.Option("files", "--mode", "-m", help="'files' or 'convos'."),
):
    """Auto-mine files as they appear or change (blocking)."""
    from engram.watcher import EngramWatcher
    watcher = EngramWatcher(directory, wing=wing, mode=mode)
    watcher.start()


# ---------------------------------------------------------------------------
# engram search
# ---------------------------------------------------------------------------

@app.command("search")
def cmd_search(
    query: str = typer.Argument(..., help="Search query."),
    wing: Optional[str] = typer.Option(None, "--wing", "-w"),
    room: Optional[str] = typer.Option(None, "--room", "-r"),
    n: int = typer.Option(10, "--results", "-n", help="Max results."),
    no_decay: bool = typer.Option(False, "--no-decay", help="Disable recency weighting."),
    hybrid: Optional[bool] = typer.Option(
        None, "--hybrid/--no-hybrid",
        help="Boost results that share the query's keywords (default: on, from config)."),
    hybrid_weight: float = typer.Option(0.3, "--hybrid-weight", help="Keyword boost weight used with --hybrid."),
    rerank: Optional[bool] = typer.Option(
        None, "--rerank/--no-rerank",
        help="Reorder top results with the local reranker model (default: from config, off)."),
):
    """Semantic search across the château."""
    searcher = _searcher()
    results = searcher.search(query, n=n, wing=wing, room=room, no_decay=no_decay,
                              hybrid_weight=None if hybrid is None else (hybrid_weight if hybrid else 0.0),
                              rerank=rerank)

    if not results:
        console.print("[yellow]No results found.[/yellow]")
        return

    import math

    # When the reranker ordered the results, show its score (as a 0-1 relevance)
    # so the column agrees with the order.
    reranked = any("rerank_score" in r for r in results)
    table = Table(title=f"Search: '{query}'" + (" (reranked)" if reranked else ""),
                  show_header=True, header_style="bold cyan")
    table.add_column("#", style="dim", width=3)
    table.add_column("Relevance" if reranked else "Score", width=9 if reranked else 7)
    table.add_column("ID", style="dim", width=13, no_wrap=True)
    table.add_column("Wing/Room/Hall", width=28)
    table.add_column("Content", overflow="fold")

    for i, r in enumerate(results, 1):
        meta = r.get("metadata", {})
        loc = f"{meta.get('wing','?')}/{meta.get('room','?')}/{meta.get('hall','?')}"
        if reranked:
            rs = r.get("rerank_score")
            if rs is None:
                score_str = "—"
            else:
                rel = 1 / (1 + math.exp(-rs))
                score_str = f"{rel:.3f}" if rel >= 0.001 else "<0.001"
        else:
            score_str = f"{r['final_score']:.3f}"
        pin = " 📌" if r.get("pinned") else ""
        table.add_row(str(i), score_str, short_id(r["id"]), loc + pin, _lineage_label(r) + r["text"][:120])

    console.print(table)
    if any(r.get("status") == "superseded" for r in results):
        console.print("[dim]Outdated memories are listed under what replaced them. "
                      "`engram history <ID>` shows when and why.[/dim]")


def _lineage_label(r: dict) -> str:
    """A short, escaped prefix saying whether a search result is current."""
    from rich.markup import escape
    if r.get("status") == "superseded":
        return escape(f"[outdated → {short_id(r.get('current_id') or r.get('superseded_by') or '')}] ")
    if r.get("status") == "disputed":
        return escape(f"[disputed with {', '.join(short_id(x) for x in r.get('disputed_with', []))}] ")
    if r.get("supersedes"):
        return escape(f"[current, replaces {', '.join(short_id(x) for x in r['supersedes'])}] ")
    return ""


# ---------------------------------------------------------------------------
# engram wake-up
# ---------------------------------------------------------------------------

@app.command("wake-up")
def cmd_wake_up(
    wing: Optional[str] = typer.Option(None, "--wing", "-w", help="Wing for L1 rebuild."),
    rebuild: bool = typer.Option(False, "--rebuild", help="Rebuild L1 from drawers."),
):
    """Print L0 + L1 context (cold-start memory load, ~170 tokens)."""
    from engram.layers import LayerStack
    palace = _palace()
    searcher = _searcher(palace=palace)
    stack = LayerStack(palace, searcher)
    ctx = stack.wake_up(wing=wing, rebuild_l1=rebuild)
    console.print(Panel(ctx, title="[bold cyan]Engram Wake-Up Context[/bold cyan]", border_style="cyan"))


# ---------------------------------------------------------------------------
# engram compress
# ---------------------------------------------------------------------------

@app.command("compress")
def cmd_compress(
    wing: Optional[str] = typer.Option(None, "--wing", "-w", help="Wing to compress."),
    room: Optional[str] = typer.Option(None, "--room", "-r", help="Room to compress."),
):
    """Rebuild ES closets for wings/rooms."""
    from engram.chateau import HALL_TYPES, Closet
    from engram.shorthand import compress as es_compress
    palace = _palace()

    wings_to_process = [w.name for w in palace.list_wings()] if not wing else [wing]
    total = 0

    for wname in wings_to_process:
        rooms = palace.list_rooms(wname) if not room else [palace.get_room(wname, room)]
        for r in rooms:
            if not r:
                continue
            for hall in HALL_TYPES:
                drawers = list(palace.iter_drawers(wing=wname, room=r.name, hall=hall))
                if not drawers:
                    continue
                combined = "\n".join(d.content for d in drawers[:20])
                closet = Closet(
                    content=es_compress(combined),
                    wing=wname,
                    room=r.name,
                    hall=hall,
                )
                palace.save_closet(closet)
                total += 1

    console.print(f"[green]✓[/green] Rebuilt [bold]{total}[/bold] closet(s).")


# ---------------------------------------------------------------------------
# engram kg
# ---------------------------------------------------------------------------

kg_app = typer.Typer(help="Knowledge graph operations.")
app.add_typer(kg_app, name="kg")


@kg_app.command("query")
def cmd_kg_query(
    entity: str = typer.Argument(..., help="Entity to look up."),
    active_only: bool = typer.Option(True, "--active/--all", help="Show only active triples."),
):
    """Query the temporal knowledge graph for an entity."""
    kg = _kg()
    triples = kg.query(entity, active_at=None if not active_only else "now")
    if not triples:
        console.print(f"[yellow]No triples found for '{entity}'.[/yellow]")
        return
    table = Table(title=f"KG: {entity}", header_style="bold")
    table.add_column("Subject")
    table.add_column("Predicate")
    table.add_column("Object")
    table.add_column("From")
    table.add_column("Until")
    for t in triples:
        style = "green" if t.is_active() else "dim"
        table.add_row(t.subject, t.predicate, t.object, t.valid_from or "", t.valid_until or "", style=style)
    console.print(table)


@kg_app.command("add")
def cmd_kg_add(
    subject: str = typer.Argument(...),
    predicate: str = typer.Argument(...),
    obj: str = typer.Argument(...),
    from_date: Optional[str] = typer.Option(None, "--from"),
    until: Optional[str] = typer.Option(None, "--until"),
):
    """Add a triple to the knowledge graph."""
    kg = _kg()
    t = kg.add(subject, predicate, obj, valid_from=from_date, valid_until=until, source="cli")
    console.print(f"[green]✓[/green] Added: {t.subject} {t.predicate} {t.object}")


@kg_app.command("invalidate")
def cmd_kg_invalidate(
    subject: str = typer.Argument(...),
    predicate: str = typer.Argument(...),
    obj: str = typer.Argument(...),
    ended: Optional[str] = typer.Option(None, "--ended"),
):
    """Mark a triple as no longer valid."""
    kg = _kg()
    count = kg.invalidate(subject, predicate, obj, ended=ended)
    console.print(f"[green]✓[/green] Invalidated {count} triple(s).")


@kg_app.command("timeline")
def cmd_kg_timeline(
    entity: str = typer.Argument(..., help="Entity to show timeline for."),
):
    """Show chronological timeline for an entity."""
    kg = _kg()
    triples = kg.timeline(entity)
    if not triples:
        console.print(f"[yellow]No timeline data for '{entity}'.[/yellow]")
        return
    for t in triples:
        active = "[green]active[/green]" if t.is_active() else "[dim]expired[/dim]"
        console.print(
            f"  [{t.valid_from or '?'}] {t.subject} [bold]{t.predicate}[/bold] {t.object} {active}"
        )


# ---------------------------------------------------------------------------
# engram answer
# ---------------------------------------------------------------------------

@app.command("answer")
def cmd_answer(
    question: str = typer.Argument(..., help="Question to answer from memory."),
    wing: Optional[str] = typer.Option(None, "--wing", "-w", help="Scope search to a wing."),
    model: Optional[str] = typer.Option(None, "--model", "-m", help="Model to use (default: llm_api_model, else llama3.2)."),
    chunks: int = typer.Option(5, "--chunks", "-k", help="Number of memory chunks to retrieve."),
):
    """Answer a question grounded in Engram memory.

    Uses the OpenAI-compatible server in llm_api_url (uzu, LM Studio, llama.cpp...)
    if set, otherwise Ollama if available.
    """
    from engram.qa import AnswerConfig, AnswerGenerator, LLMConfigError, llm_settings

    cfg = load_config()
    palace = _palace()
    backend = _backend(cfg)
    searcher = _searcher(palace=palace, backend=backend, cfg=cfg)

    try:
        fields = llm_settings(cfg)
    except LLMConfigError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1)
    if model:
        fields["llm_model"] = model
    config = AnswerConfig(max_context_chunks=chunks, **fields)
    generator = AnswerGenerator(searcher, config)

    with console.status("Searching memory and generating answer..."):
        result = generator.generate(question, wing=wing)

    console.print(f"\n[bold cyan]Question:[/bold cyan] {question}\n")
    console.print(Panel(result["answer"], title="[bold green]Answer[/bold green]", border_style="green"))

    if result["citations"]:
        table = Table(title="Memory Sources", show_header=True, header_style="bold dim")
        table.add_column("#", width=3)
        table.add_column("Score", width=7)
        table.add_column("Excerpt", overflow="fold")
        for c in result["citations"][:3]:
            table.add_row(str(c["id"]), f"{c['relevance_score']:.3f}", c["text"])
        console.print(table)

    console.print(
        f"\n[dim]Confidence: {result['confidence']:.2f} | "
        f"{result['memory_count']} memories retrieved[/dim]"
    )


# ---------------------------------------------------------------------------
# engram remember-type
# ---------------------------------------------------------------------------

@app.command("remember-type")
def cmd_remember_type(
    content: str = typer.Argument(..., help="Memory content to store."),
    type: str = typer.Argument(..., help="Memory type (run 'engram remember-type --list' for options)."),
    wing: str = typer.Option(..., "--wing", "-w", help="Wing to store in."),
    room: Optional[str] = typer.Option(None, "--room", "-r", help="Room override (defaults to type name)."),
    confidence: float = typer.Option(0.8, "--confidence", "-c", min=0.0, max=1.0),
    source: str = typer.Option("user", "--source", "-s", help="Source: user | ai | miner | conversation"),
    list_types: bool = typer.Option(False, "--list", help="List all valid memory types and exit."),
):
    """Store a typed, validated memory in the château."""
    from engram.typed_memory import MemoryType, TypedMemory, TypedMemoryStore

    if list_types:
        console.print("[bold]Valid memory types:[/bold]")
        for t in MemoryType:
            console.print(f"  [cyan]{t.value}[/cyan]")
        return

    try:
        mem_type = MemoryType.from_string(type)
    except ValueError as exc:
        console.print(f"[red]Error:[/red] {exc}")
        raise typer.Exit(1)

    memory = TypedMemory(
        content=content,
        memory_type=mem_type,
        confidence=confidence,
        source=source,
    )

    cfg = load_config()
    palace = _palace()
    backend = _backend(cfg)
    store = TypedMemoryStore(palace, backend)

    try:
        drawer_id = store.add(memory, wing=wing, room=room)
    except ValueError as exc:
        console.print(f"[red]Validation failed:[/red] {exc}")
        raise typer.Exit(1)

    console.print(
        Panel(
            f"[bold]{mem_type.value.upper()}[/bold] stored in [cyan]{wing}[/cyan]\n"
            f"ID: [dim]{drawer_id}[/dim]",
            title="[green]✓ Memory saved[/green]",
            border_style="green",
        )
    )
    if confidence < 0.5:
        console.print(f"[yellow]⚠  Low confidence ({confidence:.2f}) — consider reviewing this memory.[/yellow]")



# ---------------------------------------------------------------------------
# Corrections and history (engram.lineage)
# ---------------------------------------------------------------------------

def _lineage_call(fn, *args, **kwargs):
    from engram.lineage import LineageError
    try:
        return fn(*args, **kwargs)
    except LineageError as exc:
        from rich.markup import escape
        console.print(f"[red]Error:[/red] {escape(str(exc))}", highlight=False)
        raise typer.Exit(1)


@app.command("correct")
def cmd_correct(
    memory_id: str = typer.Argument(..., help="ID (or the first 8+ characters) of the outdated memory."),
    content: str = typer.Argument(..., help="The corrected, current information."),
    reason: str = typer.Option("", "--reason", help="Why it changed."),
    source: str = typer.Option("", "--source", help="Where the correction came from: user, primary, "
                               "secondary, tool or inference (default: same as the old memory)."),
    source_ref: str = typer.Option("", "--ref", help="Citation or URL for the correction."),
    based_on: Optional[list[str]] = typer.Option(None, "--based-on", help="ID of a memory that supports "
                                                 "the correction (repeatable)."),
):
    """Save a correction that replaces an outdated memory (the old one is kept as history)."""
    from engram.lineage import correct_memory
    from engram.relations import attach_evidence, check_source, resolve_evidence
    palace = _palace()
    evidence = _lineage_call(resolve_evidence, palace, based_on)
    out = _lineage_call(correct_memory, palace, _backend(), memory_id, content, reason=reason, by="cli",
                        source=_lineage_call(check_source, source), source_ref=source_ref)
    if evidence:
        attach_evidence(palace, out["new"]["id"], evidence, by="cli")
    if out["created"]:
        console.print(f"[green]✓[/green] Saved {short_id(out['new']['id'])}, replacing {short_id(out['old']['id'])}.")
    else:
        console.print(f"Already corrected: {short_id(out['old']['id'])} → {short_id(out['new']['id'])} (nothing changed).")


@app.command("supersede")
def cmd_supersede(
    old_id: str = typer.Argument(..., help="ID of the outdated memory."),
    new_id: Optional[str] = typer.Argument(None, help="ID of the memory that replaces it."),
    reason: str = typer.Option("", "--reason", help="Why it changed."),
    undo: bool = typer.Option(False, "--undo", help="Make OLD_ID current again."),
):
    """Mark one stored memory as replacing another, or undo that with --undo."""
    from engram.lineage import Lineage, supersede_memory
    palace = _palace()
    if undo:
        drawer = _lineage_call(_find_or_fail, palace, old_id)
        if Lineage(palace.path).restore(drawer.id):
            console.print(f"[green]✓[/green] {short_id(drawer.id)} is current again.")
        else:
            console.print(f"{short_id(drawer.id)} was not replaced; nothing changed.")
        return
    if not new_id:
        console.print("[red]Error:[/red] give the ID of the replacing memory, or use --undo.")
        raise typer.Exit(1)
    out = _lineage_call(supersede_memory, palace, old_id, new_id, reason=reason, by="cli")
    verb = "now replaces" if out["created"] else "already replaced"
    console.print(f"[green]✓[/green] {short_id(out['new']['id'])} {verb} {short_id(out['old']['id'])}.")


def _find_or_fail(palace, memory_id):
    from engram.lineage import LineageError
    try:
        drawer = palace.find_drawer(memory_id)
    except LookupError as exc:
        raise LineageError(str(exc)) from exc
    if drawer is None:
        raise LineageError(f"no memory with ID {memory_id!r}")
    return drawer


@app.command("history")
def cmd_history(memory_id: str = typer.Argument(..., help="ID (or first 8+ characters) of a memory.")):
    """Show whether a memory is current, and what replaced what, when and why."""
    from rich.markup import escape

    from engram.lineage import memory_history
    h = _lineage_call(memory_history, _palace(), memory_id)
    m = h["memory"]
    colour = {"current": "green", "superseded": "yellow", "disputed": "red"}[h["status"]]
    console.print(f"[bold]{m['id']}[/bold]  {escape(m['wing'] + '/' + m['room'] + '/' + m['hall'])}  "
                  f"[{colour}]{h['status']}[/{colour}]")
    console.print(f"  {escape(m['text'][:200])}")
    if h["status"] == "superseded":
        console.print(f"  Current version: [bold]{short_id(h['current_id'])}[/bold]")
    if h["disputed_with"]:
        console.print(f"  Disputed with: {', '.join(short_id(x) for x in h['disputed_with'])}")
    if not h["history"]:
        console.print("  [dim]No corrections recorded.[/dim]")
        return
    console.print("\n[bold]History[/bold] (oldest first)")
    for step in h["history"]:
        when = step["at"][:10]
        why = f" — {escape(step['reason'])}" if step.get("reason") else ""
        console.print(f"  {when}  {short_id(step['old'])} → {short_id(step['new'])}{why}")
        if step.get("old_text"):
            console.print(f"     [dim]was:[/dim] {escape(step['old_text'][:120])}")
        if step.get("new_text"):
            console.print(f"     [dim]now:[/dim] {escape(step['new_text'][:120])}")


# ---------------------------------------------------------------------------
# Evidence and explanations (engram.relations)
# ---------------------------------------------------------------------------

@app.command("forget")
def cmd_forget(
    memory_id: str = typer.Argument(..., help="ID (or first 8+ characters) of the memory to delete."),
    yes: bool = typer.Option(False, "--yes", help="Actually delete it. Without this, only show what would happen."),
):
    """Delete a memory for good, and clean every correction and evidence link that pointed at it."""
    from rich.markup import escape

    from engram.forget import forget, plan
    palace = _palace()
    what = _lineage_call(plan, palace, memory_id)
    m = what["memory"]
    console.print(f"[bold]{m['id']}[/bold]  {escape(m['wing'] + '/' + m['room'] + '/' + m['hall'])}  {m['timestamp'][:10]}")
    console.print(f"  {escape(m['text'])}", highlight=False)
    notes = [("becomes current again", "becomes_current_again"),
             ("stops saying it replaced something", "loses_its_replaced_label"),
             ("loses its conflict mark", "conflict_marks_removed"),
             ("loses it as evidence", "memories_that_lose_it_as_evidence")]
    for label, key in notes:
        for other in what[key]:
            console.print(f"  [yellow]{label}:[/yellow] {short_id(other['id'])}  {escape(other['text'][:90])}", highlight=False)
    if not yes:
        console.print("\n[dim]Nothing was deleted. Add --yes to delete it. It can't be undone, and earlier "
                      "exports still contain it.[/dim]")
        return
    _lineage_call(forget, palace, _backend(), memory_id)
    console.print(f"[green]✓[/green] Forgot {short_id(m['id'])}.")


@app.command("link")
def cmd_link(
    memory_id: str = typer.Argument(..., help="ID (or first 8+ characters) of a memory."),
    relation: str = typer.Argument(..., help="based_on, derived_from, contradicts or supersedes."),
    target_id: str = typer.Argument(..., help="ID of the other memory."),
    reason: str = typer.Option("", "--reason", help="Why they are linked."),
    undo: bool = typer.Option(False, "--undo", help="Remove this link."),
):
    """Link two memories: A based_on B (B is evidence for A), A derived_from B, A contradicts B, A supersedes B."""
    from engram.relations import link_memories
    out = _lineage_call(link_memories, _palace(), memory_id, relation, target_id, reason=reason, by="cli",
                        undo=undo)
    a, b = short_id(out["memory"]["id"]), short_id(out["target"]["id"])
    if undo:
        console.print(f"[green]✓[/green] Removed {a} {relation} {b}." if out["removed"]
                      else f"There was no {a} {relation} {b} link; nothing changed.")
    else:
        verb = "Linked" if out["created"] else "Already linked"
        console.print(f"[green]✓[/green] {verb}: {a} {relation} {b}.")


@app.command("source")
def cmd_source(
    memory_id: str = typer.Argument(..., help="ID (or first 8+ characters) of a memory."),
    kind: str = typer.Argument(..., help="user, primary, secondary, tool or inference."),
    ref: str = typer.Option("", "--ref", help="Citation, URL or document it came from."),
):
    """Record where a memory came from."""
    from engram.relations import SOURCE_LABELS, set_source
    out = _lineage_call(set_source, _palace(), memory_id, kind, ref)
    console.print(f"[green]✓[/green] {short_id(out['memory']['id'])}: {SOURCE_LABELS[kind]}"
                  + (f" ({out['source_ref']})" if out["source_ref"] else ""), highlight=False)


def _source_text(item: dict) -> str:
    from engram.relations import SOURCE_LABELS
    label = SOURCE_LABELS.get(item.get("source") or "", "source not recorded")
    return label + (f", {item['source_ref']}" if item.get("source_ref") else "")


def _status_text(item: dict) -> str:
    if item.get("missing"):
        return "[red]missing[/red]"
    if item.get("status") == "superseded":
        return f"[yellow]OUTDATED → {short_id(item['current_id'])}[/yellow]"
    return "[red]disputed[/red]" if item.get("status") == "disputed" else ""


def _print_evidence(items: list[dict], indent: int = 2) -> None:
    from rich.markup import escape
    pad = " " * indent
    for ev in items:
        if ev.get("missing"):
            console.print(f"{pad}{ev['relation']} {short_id(ev['id'])}  [red]missing[/red]")
            continue
        console.print(f"{pad}{ev['relation']} [bold]{short_id(ev['id'])}[/bold]  {ev['timestamp'][:10]}  "
                      f"[dim]{escape(_source_text(ev))}[/dim]  {_status_text(ev)}", highlight=False)
        console.print(f"{pad}  {escape(ev['text'][:160])}", highlight=False)
        if ev.get("reason"):
            console.print(f"{pad}  [dim]why linked: {escape(ev['reason'])}[/dim]")
        _print_evidence(ev.get("evidence") or [], indent + 4)


@app.command("why")
def cmd_why(
    memory_id: str = typer.Argument(..., help="ID (or first 8+ characters) of a memory."),
    query: Optional[str] = typer.Option(None, "--query", "-q", help="The question it was found for: "
                                        "shows why search ranked it."),
    as_json: bool = typer.Option(False, "--json", help="Print the full explanation as JSON."),
):
    """Explain a memory: source, date, evidence, earlier versions, conflicts and concerns."""
    from rich.markup import escape

    from engram.relations import explain
    palace = _palace()
    out = _lineage_call(explain, palace, memory_id, query=query, searcher=_searcher(palace) if query else None)
    if as_json:
        print(json.dumps(out, indent=2, ensure_ascii=False))
        return
    m = out["memory"]
    claim = {"direct": "recorded directly", "supported": "a conclusion resting on evidence",
             "inference": "an inference"}[out["claim"]]
    console.print(f"[bold]{m['id']}[/bold]  {escape(m['wing'] + '/' + m['room'])}  {m['timestamp'][:10]}  "
                  f"{_status_text(m)}", highlight=False)
    console.print(f"  {escape(m['text'][:400])}", highlight=False)
    console.print(f"  [dim]Source:[/dim] {escape(_source_text(m))}.  [dim]Type:[/dim] {claim}.", highlight=False)
    if out.get("relevance"):
        r = out["relevance"]
        if r.get("rank"):
            parts = ", ".join(f"{k.replace('_', ' ')} {r[k]}" for k in
                              ("semantic_score", "keyword_overlap", "recency_boost", "temporal_closeness",
                               "rerank_score") if k in r)
            console.print(f"  [dim]For “{escape(r['query'])}”:[/dim] result {r['rank']} of {r['of']} "
                          f"(score {r.get('final_score')}: {parts})", highlight=False)
        if r.get("note"):
            console.print(f"  [dim]{escape(r['note'])}[/dim]")
    console.print("\n[bold]Evidence[/bold]")
    if out["evidence"]:
        _print_evidence(out["evidence"])
    else:
        console.print("  [dim]None recorded.[/dim]")
    if out["history"]:
        console.print("\n[bold]Earlier versions[/bold] (newest first)")
        for h in out["history"]:
            why = f" — {escape(h['reason'])}" if h.get("reason") else ""
            console.print(f"  {h['replaced_at'][:10]}  {short_id(h['id'])} replaced{why}")
            if not h.get("missing"):
                console.print(f"    [dim]was:[/dim] {escape(h['text'][:160])}", highlight=False)
            _print_evidence(h.get("evidence") or [], 4)
    if out["supports"]:
        console.print("\n[bold]Memories that rest on this one[/bold]")
        for s in out["supports"]:
            console.print(f"  {short_id(s['id'])} ({s['relation']})  {escape(s.get('text', '')[:120])}", highlight=False)
    if out["conflicts"]:
        console.print("\n[bold]Conflicts with[/bold]")
        for c in out["conflicts"]:
            console.print(f"  {short_id(c['id'])}  {escape(c.get('text', '')[:120])}", highlight=False)
    if out["concerns"]:
        console.print("\n[bold yellow]Needs review[/bold yellow]")
        for note in out["concerns"]:
            console.print(f"  • {escape(note)}", highlight=False)


@app.command("check")
def cmd_check(as_json: bool = typer.Option(False, "--json", help="Print the report as JSON.")):
    """Find conclusions whose evidence changed, unsupported inferences, open conflicts and broken links."""
    from rich.markup import escape

    from engram.relations import check
    report = check(_palace())
    if as_json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
        return
    if report["ok"]:
        console.print("[green]✓[/green] Nothing needs review.")
        return
    for item in report["stale_support"]:
        m, ev = item["memory"], item["evidence"]
        what = (f"was corrected (now {short_id(ev['current_id'])})" if item["problem"] == "superseded"
                else "is disputed")
        console.print(f"[yellow]Evidence changed[/yellow]  {short_id(m['id'])} rests on {short_id(ev['id'])}, "
                      f"which {what}.", highlight=False)
        console.print(f"  [dim]{escape(m['text'][:120])}[/dim]", highlight=False)
    for m in report["unsupported_inferences"]:
        console.print(f"[yellow]No evidence[/yellow]  {short_id(m['id'])} is an inference with nothing linked "
                      "as evidence.", highlight=False)
        console.print(f"  [dim]{escape(m['text'][:120])}[/dim]", highlight=False)
    for c in report["unresolved_conflicts"]:
        console.print(f"[yellow]Undecided[/yellow]  {short_id(c['a']['id'])} and {short_id(c['b']['id'])} "
                      f"conflict (since {c['since'][:10]}).", highlight=False)
    for lk in report["broken_links"]:
        console.print(f"[red]Broken link[/red]  {lk['kind']} refers to missing memory "
                      f"{', '.join(short_id(x) for x in lk['missing'])}.", highlight=False)
    console.print("\n[dim]Use `engram why <id>` for details. Nothing was changed.[/dim]")


# ---------------------------------------------------------------------------
# Backup and restore (engram.backup)
# ---------------------------------------------------------------------------

def _backup_paths() -> dict:
    from engram import agents, config, knowledge_graph
    return {"kg_path": knowledge_graph.DB_PATH, "identity_path": config.IDENTITY_PATH,
            "agents_dir": agents.AGENTS_DIR.expanduser()}


@app.command("export")
def cmd_export(dest: str = typer.Argument(..., help="Backup file to write (.json, or .json.gz to compress).")):
    """Back up every memory, correction, the knowledge graph and diaries to one file."""
    from engram.backup import export_backup
    counts = export_backup(Path(dest), _palace(), **_backup_paths())
    console.print(f"[green]✓[/green] Backed up {_n(counts['drawers'], 'memory', 'memories')}, "
                  f"{_n(counts['lineage_links'], 'correction')}, "
                  f"{_n(counts['evidence_links'], 'evidence link')} and "
                  f"{_n(counts['kg_triples'], 'knowledge-graph fact')} to {dest}")


def _n(count: int, one: str, many: str = "") -> str:
    return f"{count} {one if count == 1 else (many or one + 's')}"


@app.command("import")
def cmd_import(
    src: str = typer.Argument(..., help="Backup file made by `engram export`."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Check the file and report, without changing anything."),
    overwrite: bool = typer.Option(False, "--overwrite",
                                   help="Replace stored memories that have the same ID but different content."),
):
    """Restore a backup. The whole file is checked first; if anything is wrong, nothing changes."""
    from engram.backup import BackupError, import_backup
    cfg = load_config()
    try:
        report = import_backup(Path(src), _palace(), backend=None if dry_run else _backend(cfg),
                               overwrite=overwrite, dry_run=dry_run,
                               preference_summaries=bool(cfg.get("preference_summaries", True)),
                               **_backup_paths())
    except BackupError as exc:
        console.print(str(exc), style="red", markup=False)
        raise typer.Exit(1)
    prefix = "Would add" if dry_run else "Added"
    console.print(f"[green]✓[/green] {prefix} {_n(report['drawers_added'], 'memory', 'memories')} "
                  f"({report['drawers_skipped']} already present), "
                  f"{_n(report['lineage_links_added'], 'correction')}, "
                  f"{_n(report['evidence_links_added'], 'evidence link')}"
                  + ("" if dry_run else f", {_n(report['kg_triples_added'], 'knowledge-graph fact')}") + ".")

# ---------------------------------------------------------------------------
# engram provenance
# ---------------------------------------------------------------------------

@app.command("provenance")
def cmd_provenance(
    memory_id: str = typer.Argument(..., help="Drawer ID to inspect."),
    history: bool = typer.Option(False, "--history", "-H", help="Show full version history."),
    summary: bool = typer.Option(False, "--summary", help="Show source summary for whole château."),
):
    """Inspect provenance and version history for a memory."""
    from engram.config import get_chateau_path
    from engram.provenance import ProvenanceTracker

    tracker = ProvenanceTracker(get_chateau_path())

    if summary:
        counts = tracker.source_summary()
        table = Table(title="Provenance Source Summary", header_style="bold cyan")
        table.add_column("Source")
        table.add_column("Count", justify="right")
        for src, cnt in sorted(counts.items(), key=lambda x: -x[1]):
            table.add_row(src, str(cnt))
        console.print(table)
        return

    records = tracker.get_history(memory_id) if history else [tracker.get(memory_id)]
    records = [r for r in records if r is not None]

    if not records:
        console.print(f"[yellow]No provenance record found for '{memory_id}'.[/yellow]")
        raise typer.Exit(1)

    table = Table(title=f"Provenance: {memory_id[:16]}…", header_style="bold")
    table.add_column("Version", width=7)
    table.add_column("Source", width=12)
    table.add_column("Confidence", width=10)
    table.add_column("Created At")
    table.add_column("Edit Reason", overflow="fold")
    for r in records:
        table.add_row(
            str(r.version),
            r.source,
            f"{r.confidence:.2f}",
            r.created_at.isoformat()[:19],
            r.edit_reason or "-",
        )
    console.print(table)


# ---------------------------------------------------------------------------
# engram conflicts
# ---------------------------------------------------------------------------

@app.command("conflicts")
def cmd_conflicts():
    """Interactive TUI conflict resolver."""
    from engram.conflict import ConflictResolver
    kg = _kg()
    resolver = ConflictResolver(kg)
    resolver.resolve_tui()


# ---------------------------------------------------------------------------
# engram audit
# ---------------------------------------------------------------------------

@app.command("audit")
def cmd_audit(
    fix: bool = typer.Option(False, "--fix", help="Auto-resolve safe issues."),
):
    """Run memory health audit on the château."""
    from engram.audit import Auditor, format_report
    palace = _palace()
    kg = _kg()
    auditor = Auditor(palace, kg)

    with console.status("Running health audit..."):
        report = auditor.run()

    console.print(Panel(format_report(report), title="[bold]ENGRAM HEALTH AUDIT[/bold]", border_style="yellow"))

    if fix:
        fixed = auditor.fix_safe(report)
        console.print(f"\n[green]✓[/green] Auto-fixed {fixed} issue(s).")


# ---------------------------------------------------------------------------
# engram graph
# ---------------------------------------------------------------------------

@app.command("graph")
def cmd_graph(
    wing: Optional[str] = typer.Option(None, "--wing", "-w", help="Wing to visualize (all wings if omitted)."),
    output: str = typer.Option("memory_graph.png", "--output", "-o", help="Output image path."),
):
    """Generate a visualization of memory relationships (requires: pip install matplotlib networkx)."""
    try:
        import matplotlib.pyplot as plt  # type: ignore
        import networkx as nx  # type: ignore
    except ImportError:
        console.print("[red]❌[/red] Missing optional deps. Install with: [cyan]pip install matplotlib networkx[/cyan]")
        raise typer.Exit(1)

    palace = _palace()
    G: nx.Graph = nx.Graph()

    wings = [wing] if wing else [w.name for w in palace.list_wings()]

    for wname in wings:
        G.add_node(wname, kind="wing", color="gold")
        for room in palace.list_rooms(wname):
            room_node = f"{wname}/{room.name}"
            G.add_node(room_node, kind="room", color="lightblue")
            G.add_edge(wname, room_node)

            for drawer in palace.iter_drawers(wing=wname, room=room.name):
                # Add typed-memory nodes only (tagged with type:*)
                mem_type = next(
                    (t.split(":", 1)[1] for t in drawer.tags if t.startswith("type:")),
                    None,
                )
                if mem_type:
                    type_node = f"{room_node}/{mem_type}"
                    if not G.has_node(type_node):
                        G.add_node(type_node, kind="type", color="lightgreen")
                        G.add_edge(room_node, type_node)

    if not G.nodes:
        console.print("[yellow]No memory nodes to visualize.[/yellow]")
        raise typer.Exit(0)

    colors = [G.nodes[n].get("color", "white") for n in G.nodes]
    plt.figure(figsize=(14, 9))
    pos = nx.spring_layout(G, seed=42, k=0.8)
    nx.draw(
        G, pos,
        with_labels=True,
        node_color=colors,
        edge_color="gray",
        font_size=8,
        node_size=800,
    )
    plt.title(f"Engram Memory Graph{' — ' + wing if wing else ''}")
    plt.tight_layout()
    plt.savefig(output, dpi=150)
    console.print(f"[green]✓[/green] Graph saved to [cyan]{output}[/cyan] ({G.number_of_nodes()} nodes, {G.number_of_edges()} edges)")


# ---------------------------------------------------------------------------
# engram replay
# ---------------------------------------------------------------------------

@app.command("replay")
def cmd_replay(
    room: str = typer.Option(..., "--room", "-r", help="Room to replay."),
    wing: Optional[str] = typer.Option(None, "--wing", "-w"),
    limit: int = typer.Option(100, "--limit", "-l", help="Max drawers to show."),
    memory_type: Optional[str] = typer.Option(None, "--type", "-t", help="Filter by memory type (fact, decision, …)."),
    since: Optional[str] = typer.Option(None, "--since", help="Show memories on or after date (YYYY-MM-DD)."),
    min_confidence: float = typer.Option(0.0, "--min-confidence", min=0.0, max=1.0, help="Minimum confidence score."),
):
    """Reconstruct chronological story of a room, with optional type/date/confidence filters."""
    from datetime import datetime, timezone

    from engram.typed_memory import MemoryType

    # Validate type filter early
    type_filter: Optional[str] = None
    if memory_type:
        try:
            type_filter = MemoryType.from_string(memory_type).value
        except ValueError as exc:
            console.print(f"[red]Error:[/red] {exc}")
            raise typer.Exit(1)

    # Parse since date
    since_dt: Optional[datetime] = None
    if since:
        try:
            since_dt = datetime.fromisoformat(since).replace(tzinfo=timezone.utc)
        except ValueError:
            console.print("[red]Error:[/red] --since must be YYYY-MM-DD or a full ISO datetime.")
            raise typer.Exit(1)

    palace = _palace()
    drawers = list(palace.iter_drawers(wing=wing, room=room))

    if not drawers:
        console.print(f"[yellow]No memories found for room '{room}'" + (f" in wing '{wing}'" if wing else "") + ".[/yellow]")
        return

    # Apply filters
    if type_filter:
        tag_match = f"type:{type_filter}"
        drawers = [d for d in drawers if tag_match in d.tags]

    if since_dt:
        def _ts(d) -> datetime:
            try:
                dt = datetime.fromisoformat(d.timestamp)
                return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt
            except (ValueError, TypeError):
                return datetime.min.replace(tzinfo=timezone.utc)
        drawers = [d for d in drawers if _ts(d) >= since_dt]

    if min_confidence > 0.0:
        # Confidence is stored as a tag token "src:" but the numeric value lives in
        # backend metadata.  Best-effort: filter by ES star rating in content.
        import re as _re
        star_threshold = max(1, min(5, int(min_confidence * 4) + 1))
        min_stars = "★" * star_threshold
        drawers = [d for d in drawers if _re.search(r"\[★+\]", d.content) is None
                   or len(_re.search(r"\[(★+)\]", d.content).group(1)) >= len(min_stars)]  # type: ignore[union-attr]

    if not drawers:
        console.print("[yellow]No memories matched the given filters.[/yellow]")
        return

    drawers.sort(key=lambda d: d.timestamp)
    drawers = drawers[:limit]

    # Display
    table = Table(
        title=f"Replay: {room}" + (f" [{type_filter}]" if type_filter else ""),
        show_header=True,
        header_style="bold cyan",
    )
    table.add_column("Timestamp", width=17, style="dim")
    table.add_column("Hall", width=12)
    table.add_column("Content", overflow="fold")

    for d in drawers:
        text = d.text()
        if len(text) > 200:
            text = text[:197] + "..."
        table.add_row(d.timestamp[:16], d.hall, text)

    console.print(table)
    console.print(f"\n[dim]{len(drawers)} memories displayed[/dim]")


# ---------------------------------------------------------------------------
# engram status
# ---------------------------------------------------------------------------

@app.command("status")
def cmd_status():
    """Show château overview."""
    palace = _palace()
    stats = palace.stats()
    cfg = load_config()

    table = Table(title="[bold cyan]Engram Château Status[/bold cyan]", show_header=False)
    table.add_column("Key", style="bold")
    table.add_column("Value", style="cyan")
    table.add_row("Wings", str(stats["wings"]))
    table.add_row("Rooms", str(stats["rooms"]))
    table.add_row("Drawers", str(stats["drawers"]))
    table.add_row("Closets", str(stats["closets"]))
    table.add_row("Backend", cfg.get("vector_backend", "chromadb"))
    table.add_row("Palace path", str(get_chateau_path()))
    console.print(table)


# ---------------------------------------------------------------------------
# engram split
# ---------------------------------------------------------------------------

@app.command("split")
def cmd_split(
    directory: str = typer.Argument(..., help="Directory with concatenated transcripts."),
    dry_run: bool = typer.Option(False, "--dry-run"),
):
    """Split concatenated conversation transcripts into individual files."""
    import re
    src = Path(directory).expanduser()
    if not src.exists():
        console.print(f"[red]Not found:[/red] {src}")
        raise typer.Exit(1)

    _SPLIT_RE = re.compile(r"(?m)^---+\s*$|(?m)^={3,}\s*$")
    total_splits = 0

    for fpath in sorted(src.rglob("*.md")):
        text = fpath.read_text(encoding="utf-8", errors="replace")
        parts = _SPLIT_RE.split(text)
        if len(parts) <= 1:
            continue
        if dry_run:
            console.print(f"  [dim]{fpath.name}[/dim] → {len(parts)} parts (dry run)")
            continue
        for j, part in enumerate(parts):
            if not part.strip():
                continue
            out = fpath.parent / f"{fpath.stem}_{j+1}.md"
            out.write_text(part.strip())
            total_splits += 1

    if dry_run:
        console.print("[dim]Dry run — no files written.[/dim]")
    else:
        console.print(f"[green]✓[/green] Created {total_splits} split file(s).")


# ---------------------------------------------------------------------------
# engram ui
# ---------------------------------------------------------------------------

@app.command("ui")
def cmd_ui(
    port: int = typer.Option(7741, "--port", "-p", help="Local port to serve the UI on."),
    no_open: bool = typer.Option(False, "--no-open", help="Skip auto-opening browser."),
):
    """Launch the Engram web UI in your browser (serves ui.html on a local port)."""
    import http.server
    import threading
    import time
    import webbrowser

    ui_file = Path(__file__).parent / "ui.html"
    if not ui_file.exists():
        console.print("[red]ui.html not found alongside cli.py[/red]")
        raise typer.Exit(1)

    serve_dir = ui_file.parent

    class _Handler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(serve_dir), **kwargs)

        def log_message(self, fmt, *args):
            pass  # silence access log

        def do_GET(self):
            if self.path == "/" or self.path == "":
                self.path = "/ui.html"
            super().do_GET()

    server = http.server.HTTPServer(("127.0.0.1", port), _Handler)
    url = f"http://127.0.0.1:{port}/"

    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    console.print(Panel(
        f"[bold]{url}[/bold]\n\n"
        "[dim]All data stays in your browser's localStorage — nothing leaves your machine.\n"
        "Press [bold]Ctrl+C[/bold] to stop.[/dim]",
        title="[bold #8a7ef4]⬡ Engram UI[/bold #8a7ef4]",
        border_style="#1f1f38",
    ))

    if not no_open:
        time.sleep(0.3)
        webbrowser.open(url)

    try:
        thread.join()
    except KeyboardInterrupt:
        server.shutdown()
        console.print("\n[dim]Engram UI stopped.[/dim]")


@app.command("install-hooks")
def cmd_install_hooks(
    dest: Path = typer.Option(
        Path("~/.engram/hooks"), "--dest", help="Directory to copy the hook scripts into."
    ),
    apply: bool = typer.Option(
        False, "--apply", help="Add the hooks to ~/.claude/settings.json yourself (a backup is kept)."
    ),
    settings_path: Path = typer.Option(
        Path("~/.claude/settings.json"), "--settings", help="Claude Code settings file to update with --apply."
    ),
    no_recall: bool = typer.Option(False, "--no-recall", help="Leave out auto-recall."),
):
    """Install the Claude Code hooks: auto-save, pre-compact save, and auto-recall.

    Auto-recall searches Engram each time you send Claude a message and adds up
    to a few clearly relevant memories to its context.
    """
    import json
    import shutil
    import sys

    src_dir = Path(__file__).parent / "hooks"
    target = dest.expanduser()
    target.mkdir(parents=True, exist_ok=True)
    installed = {}
    for script in ("engram_save_hook.sh", "engram_precompact_hook.sh"):
        out = target / script
        shutil.copyfile(src_dir / script, out)
        out.chmod(0o755)
        installed[script] = str(out)

    snippet = hook_settings(installed, recall_command=None if no_recall else recall_command(),
                            python=sys.executable)
    console.print(f"[green]✓[/green] Hooks copied to {target}")
    if not apply:
        console.print("Add this to [bold]~/.claude/settings.json[/bold] (merge with any existing hooks), "
                      "or run again with [bold]--apply[/bold] to do it for you:")
        print(json.dumps(snippet, indent=2))
        return
    path = settings_path.expanduser()
    try:
        added = merge_hook_settings(path, snippet)
    except ValueError as exc:
        console.print(f"[red]Error:[/red] {exc}", markup=False)
        raise typer.Exit(1)
    if added:
        console.print(f"[green]✓[/green] Added {added} hook(s) to {path} (previous version saved as "
                      f"{path.name}.bak). Restart Claude Code to load them.")
    else:
        console.print(f"[green]✓[/green] {path} already has the Engram hooks; nothing changed.")
    if not no_recall:
        console.print("Auto-recall is on. Preview what it would add with [bold]engram recall \"a message\"[/bold]; "
                      "turn it off with [bold]\"recall\": false[/bold] in ~/.engram/config.json.")


def recall_command() -> str:
    """The auto-recall hook command: this Python, so the hook finds Engram whatever PATH is."""
    import shlex
    import sys
    return f"{shlex.quote(sys.executable)} -m engram.recall"


def hook_settings(installed: dict, recall_command: Optional[str], python: Optional[str] = None) -> dict:
    """The Claude Code hooks settings. With *python*, the shell hooks run Engram
    through that interpreter (ENGRAM_PYTHON), so they work without `engram` on PATH."""
    import shlex

    def cmd(script: str) -> str:
        path = shlex.quote(installed[script])
        return f"ENGRAM_PYTHON={shlex.quote(python)} {path}" if python else installed[script]

    hooks = {
        "PostToolUse": [{
            "matcher": "Write|Edit|MultiEdit",
            "hooks": [{"type": "command", "command": cmd("engram_save_hook.sh")}],
        }],
        "PreCompact": [{
            "hooks": [{"type": "command", "command": cmd("engram_precompact_hook.sh")}],
        }],
    }
    if recall_command:
        hooks["UserPromptSubmit"] = [{"hooks": [{"type": "command", "command": recall_command,
                                                 "timeout": 30}]}]
    return {"hooks": hooks}


ENGRAM_HOOK_MARKERS = ("engram_save_hook.sh", "engram_precompact_hook.sh", "engram.recall")


def _is_engram_group(group) -> bool:
    return isinstance(group, dict) and any(
        isinstance(h, dict) and any(m in str(h.get("command", "")) for m in ENGRAM_HOOK_MARKERS)
        for h in group.get("hooks", []))


def merge_hook_settings(path: Path, snippet: dict) -> int:
    """Put *snippet*'s hooks into the settings file at *path*, replacing older Engram
    hooks and leaving every other setting and hook alone.

    Keeps a ``.bak`` copy and returns how many hook entries were added or
    updated (0 when it already matches). Raises ValueError if the existing
    file isn't valid JSON (it is then left untouched).
    """
    import json
    import shutil

    settings = {}
    if path.exists():
        try:
            settings = json.loads(path.read_text() or "{}")
        except ValueError as exc:
            raise ValueError(f"{path} is not valid JSON ({exc}); fix it or add the hooks by hand") from exc
    hooks = settings.setdefault("hooks", {})
    added = 0
    for event, groups in snippet["hooks"].items():
        current = hooks.get(event) if isinstance(hooks.get(event), list) else []
        ours = [g for g in current if _is_engram_group(g)]
        if ours == groups:
            continue
        hooks[event] = [g for g in current if not _is_engram_group(g)] + groups
        added += len(groups)
    if added:
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            shutil.copyfile(path, path.with_name(path.name + ".bak"))
        path.write_text(json.dumps(settings, indent=2) + "\n")
    return added


@app.command("connect")
def cmd_connect(
    target: Optional[str] = typer.Argument(
        None, help="App to connect: claude-desktop, cursor, windsurf, vscode, gemini, codex, zed, lm-studio, "
                   "claude-code, or 'all' for every one installed. Leave out to list them."),
):
    """Connect Engram's memory to an AI app (adds the MCP server to its settings, with a backup)."""
    from rich.markup import escape

    from engram import connect as cn

    known = cn.apps()
    if target is None:
        console.print("[bold]Apps Engram can connect to[/bold] (✓ = looks installed):")
        for app_ in known.values():
            mark = "[green]✓[/green]" if app_.path.parent.exists() else " "
            console.print(f"  {mark} engram connect {app_.key:15} {escape(app_.name)}")
        console.print("    engram connect claude-code     Claude Code (MCP + auto-recall hooks)")
        console.print("\nOr [bold]engram connect all[/bold] for every installed app.")
        return
    if target == "claude-code":
        command, args = cn.server_command()
        console.print("Run this, then restart Claude Code:", highlight=False)
        print(f"claude mcp add {cn.SERVER_NAME} -- {command} {' '.join(args)}")
        console.print("And for automatic recall and saving: [bold]engram install-hooks --apply[/bold]")
        return
    targets = cn.detected() if target == "all" else ([known[target]] if target in known else None)
    if targets is None:
        console.print(f"[red]Unknown app {escape(target)!r}.[/red] Run [bold]engram connect[/bold] to see the list.")
        raise typer.Exit(1)
    if not targets:
        console.print("No supported apps found. Run [bold]engram connect[/bold] to see the list.")
        return
    for app_ in targets:
        try:
            status = cn.connect(app_)
        except ValueError as exc:
            console.print(f"[yellow]{escape(app_.name)}:[/yellow] {escape(str(exc))}. Add this to "
                          f"{escape(str(app_.path))}:", highlight=False)
            print(cn.snippet(app_))
            console.print(f"  Then: {escape(app_.restart)}.")
            continue
        if status == "unchanged":
            console.print(f"[green]✓[/green] {escape(app_.name)} already has Engram.")
        else:
            console.print(f"[green]✓[/green] {escape(app_.name)}: Engram {status} in {escape(str(app_.path))} "
                          f"(backup: {escape(app_.path.name)}.bak). {escape(app_.restart)}.")


@app.command("reindex")
def cmd_reindex(wing: Optional[str] = typer.Option(None, "--wing", help="Only this wing.")):
    """Rebuild the search index from your memories (after changing the embedding model)."""
    from engram.backup import reindex
    from engram.embedding import EmbeddingConfigError
    palace, backend = _palace(), _backend()
    drawers = [d.to_dict() for d in palace.iter_drawers(wing=wing)]
    if not drawers:
        console.print("No memories to index.")
        return
    cfg = load_config()
    server = getattr(backend, "embedding_server", None) or getattr(getattr(backend, "inner", None), "embedding_server", None)
    console.print(f"Indexing {_n(len(drawers), 'memory', 'memories')}"
                  + (f" with {server['model']} at {server['url']}" if server else " with the built-in model") + " …")
    try:
        chunks = reindex(backend, drawers, bool(cfg.get("preference_summaries", True)))
    except EmbeddingConfigError as exc:
        console.print(f"[red]Error:[/red] {exc}", highlight=False)
        raise typer.Exit(1)
    console.print(f"[green]✓[/green] Indexed {_n(chunks, 'chunk')}. Your memories themselves were not changed.")


@app.command("serve")
def cmd_serve(
    host: str = typer.Option("127.0.0.1", "--host", help="Address to listen on. Anything but localhost needs a token."),
    port: int = typer.Option(7742, "--port", help="Port to listen on."),
    token: bool = typer.Option(False, "--token", help="Require a token even on localhost (created on first use)."),
    allow_host: Optional[list[str]] = typer.Option(None, "--allow-host", help="Extra Host name to accept on a "
                                                   "tokenless localhost server (e.g. host.docker.internal)."),
):
    """Run a local web API for apps that don't speak MCP (Open WebUI, n8n, scripts)."""
    from engram import server as srv
    secret = None
    if token or not srv.is_loopback(host):
        secret = srv.load_or_create_token()
    try:
        httpd = srv.make_server(host, port, secret, extra_hosts=tuple(allow_host or ()))
    except (ValueError, OSError) as exc:
        console.print(f"[red]Error:[/red] {exc}", highlight=False)
        raise typer.Exit(1)
    base = f"http://{host if ':' not in host else '[' + host + ']'}:{port}"
    console.print(f"[green]✓[/green] Engram is serving at {base}  [dim](Ctrl+C to stop)[/dim]")
    console.print(f"  Tools:    {base}/openapi.json   (point Open WebUI or n8n here)")
    if secret:
        console.print(f"  Token:    send  Authorization: Bearer <token>   — it is in {srv.token_path()}", highlight=False)
    else:
        console.print("  No token: only apps on this computer can reach it. Use --token to require one.")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        console.print("\n[dim]Engram server stopped.[/dim]")
    finally:
        httpd.server_close()


@app.command("recall")
def cmd_recall(
    message: str = typer.Argument(..., help="A message you might send Claude."),
    cwd: Optional[str] = typer.Option(None, "--cwd", help="Project folder Claude would be in (default: here)."),
):
    """Preview what auto-recall would add to Claude's context for MESSAGE."""
    import os

    from engram.recall import project_wing, recall
    folder = cwd or os.getcwd()
    project = project_wing(folder)
    if project:
        console.print(f"[dim]Project: {project} (its memories come first)[/dim]")
    note = recall(message, remember=False, cwd=folder)
    if note:
        print(note)
    else:
        console.print("[dim]Nothing relevant enough; Claude would get no extra context for this message.[/dim]")


@app.command("setup-reranker")
def cmd_setup_reranker(
    disable: bool = typer.Option(False, "--disable", help="Turn the reranker off again."),
):
    """Download the local reranker model (~90 MB, once) and turn reranking on.

    The reranker reorders the top search results with a small cross-encoder that
    runs on this machine (no API key). It raised LongMemEval R@5 from 98.2% to
    98.8% and LoCoMo R@10 from 87.4% to 88.7%. Engram never downloads the model
    by itself; this command is the only thing that does.
    """
    import json

    from engram import config as cfg_mod
    from engram import reranker as rr

    cfg_mod.ensure_engram_dir()
    path = cfg_mod.CONFIG_PATH
    saved = {}
    if path.exists():
        try:
            saved = json.loads(path.read_text())
        except (json.JSONDecodeError, OSError):
            saved = {}
    if disable:
        saved["reranker"] = False
        path.write_text(json.dumps(saved, indent=2))
        console.print("[green]✓[/green] Reranker turned off.")
        return
    try:
        model_dir = rr.ensure_model(saved.get("reranker_model", rr.DEFAULT_MODEL))
        rr.CrossEncoder(model_dir).score("test", ["test"])  # fail here, not on the first search
    except rr.RerankerUnavailable as exc:
        console.print(f"[red]Reranker setup failed:[/red] {exc}")
        raise typer.Exit(1)
    saved["reranker"] = True
    path.write_text(json.dumps(saved, indent=2))
    console.print(f"[green]✓[/green] Reranker model ready in {model_dir}")
    console.print("Reranking is on for `engram search` and the MCP server. "
                  "Turn it off with [bold]engram setup-reranker --disable[/bold].")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    app()


if __name__ == "__main__":
    main()
