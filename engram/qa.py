"""LLM-grounded question answering over Engram memory."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional


@dataclass
class AnswerConfig:
    """Configuration for the QA system."""

    llm_model: str = "llama3.2"
    llm_api_url: str = "http://localhost:11434/api/generate"
    max_context_chunks: int = 5
    temperature: float = 0.1
    use_local_llm: bool = True


class AnswerGenerator:
    """Generate answers grounded in Engram memory."""

    def __init__(self, searcher, config: Optional[AnswerConfig] = None) -> None:
        self.searcher = searcher
        self.config = config or AnswerConfig()

    def generate(self, question: str, wing: Optional[str] = None) -> dict[str, Any]:
        """Generate an answer with citations from memory."""
        results = self.searcher.search(
            question,
            n=self.config.max_context_chunks,
            wing=wing,
        )

        if not results:
            return {
                "answer": "No relevant memories found to answer this question.",
                "citations": [],
                "confidence": 0.0,
                "memory_count": 0,
            }

        context_parts: list[str] = []
        citations: list[dict] = []

        for i, result in enumerate(results, 1):
            context_parts.append(f"[{i}] {result['text']}")
            snippet = result["text"]
            citations.append(
                {
                    "id": i,
                    "text": snippet[:200] + ("..." if len(snippet) > 200 else ""),
                    "relevance_score": result.get("final_score", 0.0),
                }
            )

        context = "\n\n".join(context_parts)

        identity_path = Path.home() / ".engram" / "identity.txt"
        identity = identity_path.read_text().strip() if identity_path.exists() else ""

        prompt = self._build_prompt(question, context, identity)

        if self.config.use_local_llm and self._check_ollama():
            answer = self._query_ollama(prompt)
        else:
            answer = f"Based on memory:\n{results[0]['text']}"

        return {
            "answer": answer,
            "citations": citations,
            "confidence": results[0].get("final_score", 0.5),
            "memory_count": len(results),
        }

    # ------------------------------------------------------------------

    def _build_prompt(self, question: str, context: str, identity: str) -> str:
        identity_block = f"\n{identity}\n" if identity else ""
        return (
            f"You are an AI assistant with persistent memory.{identity_block}\n"
            f"CONTEXT FROM MEMORY:\n{context}\n\n"
            f"QUESTION: {question}\n\n"
            "INSTRUCTIONS:\n"
            "- Answer based ONLY on the provided context.\n"
            "- If the context doesn't contain the answer, say "
            '"I don\'t have that information in memory".\n'
            "- Cite relevant sources using [1], [2] etc.\n"
            "- Be concise but thorough.\n\n"
            "ANSWER:"
        )

    def _check_ollama(self) -> bool:
        try:
            result = subprocess.run(
                ["ollama", "list"],
                capture_output=True,
                text=True,
                timeout=2,
            )
            return result.returncode == 0
        except (subprocess.SubprocessError, FileNotFoundError):
            return False

    def _query_ollama(self, prompt: str) -> str:
        try:
            import requests  # type: ignore
        except ImportError:
            return "requests library not installed. Run: pip install requests"

        payload = {
            "model": self.config.llm_model,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": self.config.temperature},
        }

        try:
            response = requests.post(self.config.llm_api_url, json=payload, timeout=60)
            response.raise_for_status()
            return response.json().get("response", "Error generating answer")
        except Exception as exc:
            return f"Error querying LLM: {exc}"
