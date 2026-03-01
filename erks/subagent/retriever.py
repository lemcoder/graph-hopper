"""Retriever: embed a query, search the vector store, format as XML context."""
from __future__ import annotations

from erks.subagent.ingestion import Chunk, EmbeddingInterface
from erks.subagent.vector_store import VectorStore


class Retriever:
    """Stateless retrieval service.  Dependencies are injected at construction.

    Typical usage::

        retriever = Retriever(embedder, vector_store)
        xml_ctx = retriever.retrieve_context("how does X work?")
    """

    def __init__(self, embedder: EmbeddingInterface, vector_store: VectorStore):
        self.embedder = embedder
        self.vector_store = vector_store

    # ------------------------------------------------------------------
    # Raw retrieval
    # ------------------------------------------------------------------

    def retrieve_raw(self, query: str, k: int = 5) -> list[tuple[Chunk, float]]:
        """Return up to *k* ``(Chunk, similarity_score)`` pairs for *query*."""
        query_vector = self.embedder.embed([query])[0]
        return self.vector_store.search(query_vector, k=k)

    # ------------------------------------------------------------------
    # Context formatting
    # ------------------------------------------------------------------

    @staticmethod
    def format_context(results: list[tuple[Chunk, float]]) -> str:
        """Render a list of ``(Chunk, score)`` pairs as an XML context string."""
        if not results:
            return "<context></context>"
        parts = []
        for chunk, score in results:
            parts.append(
                f'  <document source="{chunk.url_or_path}" '
                f'doc_id="{chunk.doc_id}" '
                f'relevance_score="{score:.2f}">\n'
                f"    <chunk>\n"
                f"      {chunk.text}\n"
                f"    </chunk>\n"
                f"  </document>"
            )
        return "<context>\n" + "\n".join(parts) + "\n</context>"

    def retrieve_context(self, query: str, k: int = 5) -> str:
        """Embed *query*, search the index, and return an XML context string.

        Returns ``<context></context>`` when the store is empty or has fewer
        chunks than requested.
        """
        return self.format_context(self.retrieve_raw(query, k=k))
