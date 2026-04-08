"""Example: importing a conversation export into the château."""

from engram.config import load_config
from engram.palace import Palace
from engram.backends import get_backend
from engram.convo_miner import ConvoMiner

cfg = load_config()
palace = Palace()
backend = get_backend(cfg["vector_backend"])
cm = ConvoMiner(palace, backend, cfg)

# Mine a Claude/ChatGPT export directory
drawers = cm.mine("~/Downloads/claude-export", wing="myproject", room="design-decisions")
print(f"Imported {len(drawers)} conversation drawer(s).")

if __name__ == "__main__":
    pass
