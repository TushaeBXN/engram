"""Example: mining a project directory into the château."""

from pathlib import Path
from engram.config import load_config
from engram.palace import Palace
from engram.backends import get_backend
from engram.miner import Miner

cfg = load_config()
palace = Palace()
backend = get_backend(cfg["vector_backend"])
miner = Miner(palace, backend, cfg)

# Mine the current directory into the "myproject" wing
drawers = miner.mine(".", wing="myproject")
print(f"Mined {len(drawers)} drawer(s).")

if __name__ == "__main__":
    pass
