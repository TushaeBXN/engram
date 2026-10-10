"""Example: importing a conversation export into the château.

Usage::

    python examples/convo_import.py ~/Downloads/claude-export [--wing NAME] [--room NAME]
"""

import argparse
from pathlib import Path

from engram.backends import get_backend
from engram.chateau import Chateau
from engram.config import load_config
from engram.convo_miner import ConvoMiner


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("export_dir", type=Path, help="Claude / ChatGPT / Slack export directory")
    parser.add_argument("--wing", default="myproject")
    parser.add_argument("--room", default="design-decisions")
    args = parser.parse_args()

    cfg = load_config()
    cm = ConvoMiner(Chateau(), get_backend(cfg["vector_backend"]), cfg)
    drawers = cm.mine(args.export_dir.expanduser(), wing=args.wing, room=args.room)
    print(f"Imported {len(drawers)} conversation drawer(s).")


if __name__ == "__main__":
    main()
