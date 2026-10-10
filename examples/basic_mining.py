"""Example: mining a project directory into the château.

Usage::

    python examples/basic_mining.py [PATH] [--wing NAME]
"""

import argparse

from engram.backends import get_backend
from engram.chateau import Chateau
from engram.config import load_config
from engram.miner import Miner


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("path", nargs="?", default=".", help="directory to mine (default: .)")
    parser.add_argument("--wing", default="myproject")
    args = parser.parse_args()

    cfg = load_config()
    miner = Miner(Chateau(), get_backend(cfg["vector_backend"]), cfg)
    drawers = miner.mine(args.path, wing=args.wing)
    print(f"Mined {len(drawers)} drawer(s) into wing '{args.wing}'.")


if __name__ == "__main__":
    main()
