"""Engram CLI — full command surface via Typer + Rich.

All commands follow the spec in BRIEF.md.  Every subcommand that writes
to the terminal uses Rich for tables, panels, and progress bars.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich import print as rprint

from engram.config import load_config, get_chateau_path

app = typer.Typer(
    name="engram",
    help="The AI memory layer that never forgets.",
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
    from engram.backends import get_backend
    c = cfg or load_config()
    return get_backend(c.get("vector_backend", "chromadb"))


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
    since: Optional[str] = typer.Option(None, "--since", help="Skip files older than ISO date."),
    plugin: Optional[str] = typer.Option(None, "--plugin", "-p", help="Plugin: obsidian | notion | linear"),
):
    """Mine a directory into the château."""
    cfg = load_config()
    palace = _palace()
    backend = _backend(cfg)

    if plugin:
        from engram.plugins import get_plugin
        from engram.miner import Miner
        plug = get_plugin(plugin)
        with console.status(f"Fetching from [cyan]{directory}[/cyan] via [bold]{plugin}[/bold]..."):
            docs = plug.fetch(directory)
        miner = Miner(palace, backend, cfg)
        drawers = []
        for doc in docs:
            from engram.chateau import Drawer
            d = Drawer(
                content=doc["content"][:4000],
                wing=wing,
                room=Path(doc["metadata"].get("path", "unknown")).stem,
                hall="facts",
                timestamp=doc["timestamp"] or "",
                tags=["plugin", plugin],
            )
            palace.save_drawer(d)
            backend.add(d.id, doc["content"][:2000], {
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
            drawers = miner.mine(directory, wing=wing, mode=mode, since=since)
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
):
    """Semantic search across the château."""
    searcher = _searcher()
    results = searcher.search(query, n=n, wing=wing, room=room, no_decay=no_decay)

    if not results:
        console.print("[yellow]No results found.[/yellow]")
        return

    table = Table(title=f"Search: '{query}'", show_header=True, header_style="bold cyan")
    table.add_column("#", style="dim", width=3)
    table.add_column("Score", width=7)
    table.add_column("Wing/Room/Hall", width=28)
    table.add_column("Content", overflow="fold")

    for i, r in enumerate(results, 1):
        meta = r.get("metadata", {})
        loc = f"{meta.get('wing','?')}/{meta.get('room','?')}/{meta.get('hall','?')}"
        score_str = f"{r['final_score']:.3f}"
        pin = " 📌" if r.get("pinned") else ""
        table.add_row(str(i), score_str, loc + pin, r["text"][:120])

    console.print(table)


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
    from engram.shorthand import compress as es_compress
    from engram.chateau import Closet, HALL_TYPES
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
    model: str = typer.Option("llama3.2", "--model", "-m", help="Ollama model to use."),
    chunks: int = typer.Option(5, "--chunks", "-k", help="Number of memory chunks to retrieve."),
):
    """Answer a question grounded in Engram memory (uses Ollama if available)."""
    from engram.qa import AnswerConfig, AnswerGenerator

    cfg = load_config()
    palace = _palace()
    backend = _backend(cfg)
    searcher = _searcher(palace=palace, backend=backend, cfg=cfg)

    config = AnswerConfig(llm_model=model, max_context_chunks=chunks)
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
# engram replay
# ---------------------------------------------------------------------------

@app.command("replay")
def cmd_replay(
    room: str = typer.Option(..., "--room", "-r", help="Room to replay."),
    wing: Optional[str] = typer.Option(None, "--wing", "-w"),
    limit: int = typer.Option(100, "--limit", "-l", help="Max drawers to show."),
):
    """Reconstruct chronological story of a room."""
    from engram.replay import Replayer
    palace = _palace()
    replayer = Replayer(palace)
    story = replayer.replay(room, wing=wing, limit=limit)
    console.print(story)


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
# Entry point
# ---------------------------------------------------------------------------

def main():
    app()


if __name__ == "__main__":
    main()
