"""Guided init + ES bootstrap.

Runs when the user first calls ``engram init <dir>``.  Walks them through:

1. Creating ~/.engram/ and default config
2. Setting their L0 identity text
3. Configuring the default wing
4. Choosing a vector backend
5. Optionally running an initial mine on the target directory

Usage::

    onboarder = Onboarder()
    onboarder.run("/path/to/project")
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from rich.console import Console
from rich.panel import Panel

from engram.config import (
    ensure_engram_dir,
    save_config,
    save_wing_config,
    load_config,
    ENGRAM_DIR,
    IDENTITY_PATH,
)

console = Console()


class Onboarder:
    """Guided onboarding flow for new Engram installations."""

    def __init__(self) -> None:
        self.cfg = load_config()

    def run(self, project_dir: Optional[str] = None) -> None:
        """Run the full interactive onboarding flow."""
        ensure_engram_dir()

        console.print(
            Panel(
                "[bold cyan]Welcome to Engram[/bold cyan] — the AI memory layer that never forgets.\n\n"
                "This will set up your personal memory château at [bold]~/.engram/[/bold].\n"
                "It takes about 2 minutes.",
                title="🏰 Engram Setup",
                border_style="cyan",
            )
        )

        self._setup_identity()
        self._setup_wing(project_dir)
        self._choose_backend()
        self._write_config()

        if project_dir:
            self._offer_initial_mine(project_dir)

        console.print(
            "\n[bold green]✓ Château initialised![/bold green]\n\n"
            "Next steps:\n"
            "  [cyan]engram wake-up[/cyan]               ← load L0+L1 context\n"
            "  [cyan]engram mine <dir>[/cyan]             ← mine a project\n"
            "  [cyan]engram search \"your query\"[/cyan]   ← semantic search\n"
        )

    # ------------------------------------------------------------------

    def _setup_identity(self) -> None:
        console.print("\n[bold]Step 1/4 — Identity[/bold]")
        console.print(
            "Write 1–2 sentences describing this AI's role.  "
            "This becomes your L0 context loaded every session.\n"
            "[dim]Example: I am Claude, an AI assistant helping Tushae build Engram. "
            "My focus is backend Python, API design, and memory systems.[/dim]\n"
        )
        try:
            identity = input("Identity text (press Enter to skip): ").strip()
        except (EOFError, KeyboardInterrupt):
            identity = ""

        if identity:
            IDENTITY_PATH.parent.mkdir(parents=True, exist_ok=True)
            IDENTITY_PATH.write_text(identity)
            console.print(f"  [green]✓[/green] Identity saved to {IDENTITY_PATH}")
        else:
            console.print("  [dim]Skipped — run `engram init` again to set identity later.[/dim]")

    def _setup_wing(self, project_dir: Optional[str] = None) -> None:
        console.print("\n[bold]Step 2/4 — Default Wing[/bold]")
        suggestion = ""
        if project_dir:
            suggestion = Path(project_dir).expanduser().name
        console.print(
            "Wings organise memories by person or project.  "
            f"[dim]Suggestion: {suggestion or 'myproject'}[/dim]\n"
        )
        try:
            wing = input(f"Wing name [{suggestion or 'default'}]: ").strip()
        except (EOFError, KeyboardInterrupt):
            wing = ""

        wing = wing or suggestion or "default"
        self.cfg["default_wing"] = wing

        # Create wing in palace
        from engram.palace import Palace
        palace = Palace()
        palace.create_wing(wing, description=f"Initialised via engram init")
        console.print(f"  [green]✓[/green] Wing '[bold]{wing}[/bold]' created.")

    def _choose_backend(self) -> None:
        console.print("\n[bold]Step 3/4 — Vector Backend[/bold]")
        console.print(
            "  [bold]chromadb[/bold]   — recommended, best quality (default)\n"
            "  [bold]faiss[/bold]      — fastest, requires faiss-cpu\n"
            "  [bold]sqlitevec[/bold]  — zero-dependency fallback\n"
        )
        try:
            backend = input("Backend [chromadb]: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            backend = ""

        if backend not in ("chromadb", "faiss", "sqlitevec", ""):
            console.print("  [yellow]Unknown backend — defaulting to chromadb.[/yellow]")
            backend = "chromadb"
        self.cfg["vector_backend"] = backend or "chromadb"
        console.print(f"  [green]✓[/green] Backend set to [bold]{self.cfg['vector_backend']}[/bold].")

    def _write_config(self) -> None:
        console.print("\n[bold]Step 4/4 — Saving config[/bold]")
        save_config(self.cfg)
        console.print(f"  [green]✓[/green] Config written to {ENGRAM_DIR / 'config.json'}")

        # Bootstrap L1 empty file
        l1_path = ENGRAM_DIR / "l1_facts.es"
        if not l1_path.exists():
            l1_path.write_text("# L1 critical facts — populated by `engram wake-up`\n")

    def _offer_initial_mine(self, project_dir: str) -> None:
        console.print(f"\n[bold]Mine '{project_dir}' now?[/bold]")
        try:
            answer = input("Run initial mine? [y/N]: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            answer = "n"

        if answer == "y":
            from engram.palace import Palace
            from engram.backends import get_backend
            from engram.miner import Miner
            palace = Palace()
            backend = get_backend(self.cfg.get("vector_backend", "chromadb"))
            miner = Miner(palace, backend, self.cfg)
            wing = self.cfg.get("default_wing", "default")
            with console.status(f"Mining [cyan]{project_dir}[/cyan]..."):
                drawers = miner.mine(project_dir, wing=wing)
            console.print(f"  [green]✓[/green] Mined {len(drawers)} drawer(s).")


if __name__ == "__main__":
    import sys
    project = sys.argv[1] if len(sys.argv) > 1 else None
    Onboarder().run(project)
