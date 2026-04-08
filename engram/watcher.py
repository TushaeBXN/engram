"""Watch mode — auto-mines files as they appear or change.

Uses the ``watchdog`` library to listen for filesystem events.
Each new or modified file is passed to the appropriate miner.

Usage::

    watcher = EngramWatcher("~/chats/", wing="myapp", mode="convos")
    watcher.start()   # blocks until Ctrl-C

CLI::

    engram watch ~/chats/ --wing myapp --mode convos
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Optional

from engram.config import load_config


class EngramWatcher:
    """Watches a directory and mines new/modified files automatically.

    Args:
        path:         Directory to watch.
        wing:         Wing to assign mined drawers to.
        mode:         ``"files"`` or ``"convos"``.
        chateau_path:  Override default palace path.
        config:       Override config dict.
    """

    def __init__(
        self,
        path: str | Path,
        wing: Optional[str] = None,
        mode: str = "files",
        chateau_path: Optional[Path] = None,
        config: Optional[dict] = None,
    ) -> None:
        self.path = Path(path).expanduser()
        self.wing = wing or "default"
        self.mode = mode
        self.config = config or load_config()
        self._chateau_path = chateau_path
        self._observer = None
        self._running = False

    # ------------------------------------------------------------------

    def start(self) -> None:
        """Start watching (blocking).  Press Ctrl-C to stop."""
        from watchdog.observers import Observer  # type: ignore
        from watchdog.events import FileSystemEventHandler  # type: ignore
        from engram.chateau import Chateau
        from engram.backends import get_backend
        from engram.miner import Miner
        from rich.console import Console
        from rich import print as rprint

        console = Console()
        palace = Chateau(self._chateau_path)
        backend = get_backend(self.config.get("vector_backend", "chromadb"))
        miner = Miner(palace, backend, self.config)

        watcher = self

        class _Handler(FileSystemEventHandler):
            def on_created(self, event):
                if not event.is_directory:
                    watcher._handle_event("created", event.src_path, miner, console)

            def on_modified(self, event):
                if not event.is_directory:
                    watcher._handle_event("modified", event.src_path, miner, console)

        observer = Observer()
        observer.schedule(_Handler(), str(self.path), recursive=True)
        observer.start()
        self._observer = observer
        self._running = True

        console.print(
            f"[bold green]Engram Watcher[/bold green] — watching [cyan]{self.path}[/cyan] "
            f"(wing=[yellow]{self.wing}[/yellow], mode=[yellow]{self.mode}[/yellow])"
        )
        console.print("Press [bold]Ctrl-C[/bold] to stop.\n")

        try:
            while self._running:
                time.sleep(1)
        except KeyboardInterrupt:
            pass
        finally:
            observer.stop()
            observer.join()
            console.print("\n[bold red]Watcher stopped.[/bold red]")

    def stop(self) -> None:
        """Signal the watcher to stop (call from another thread)."""
        self._running = False
        if self._observer:
            self._observer.stop()

    # ------------------------------------------------------------------

    def _handle_event(self, event_type: str, src_path: str, miner, console) -> None:
        path = Path(src_path)
        if path.suffix not in {".py", ".js", ".ts", ".md", ".txt", ".json", ".yaml"}:
            return  # skip binary files

        try:
            drawers = miner.mine(
                path,
                wing=self.wing,
                mode=self.mode,
            )
            if drawers:
                console.print(
                    f"  [green]✓[/green] [{event_type}] {path.name} "
                    f"→ [bold]{len(drawers)}[/bold] drawer(s) mined"
                )
        except Exception as exc:
            console.print(f"  [red]✗[/red] {path.name} — {exc}")


if __name__ == "__main__":
    import sys
    p = sys.argv[1] if len(sys.argv) > 1 else "."
    w = EngramWatcher(p, wing="default", mode="files")
    w.start()
