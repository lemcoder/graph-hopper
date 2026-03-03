"""Hybrid confidence scorer: 70% cosine similarity + 30% keyword overlap."""

from __future__ import annotations

import string


class ConfidenceScorer:
    """Compute a [0.0, 1.0] confidence score for a retrieved chunk.

    The score combines:
    - 70 % cosine similarity (passed in directly from the vector search)
    - 30 % keyword overlap (proportion of query keywords found in the chunk)
    """

    DEFAULT_STOP_WORDS: frozenset[str] = frozenset(
        {"the", "and", "is", "in", "it", "of", "to", "a", "for", "on", "with"}
    )

    def __init__(self, stop_words: set[str] | None = None):
        self.stop_words: frozenset[str] = (
            frozenset(stop_words) if stop_words is not None else self.DEFAULT_STOP_WORDS
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def score(self, query: str, chunk_text: str, vector_score: float) -> float:
        """Return a hybrid confidence score in [0.0, 1.0].

        Parameters
        ----------
        query:        The user's raw query string.
        chunk_text:   The retrieved chunk's text.
        vector_score: Cosine similarity from the vector search (can be < 0).
        """
        query_kw = self._preprocess(query)
        chunk_kw = self._preprocess(chunk_text)

        if not query_kw:
            overlap_score = 0.0
        else:
            overlap_score = len(query_kw & chunk_kw) / len(query_kw)

        raw = (vector_score * 0.7) + (overlap_score * 0.3)
        return max(0.0, min(1.0, raw))

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _preprocess(self, text: str) -> set[str]:
        """Lowercase, strip punctuation, split, remove stop words."""
        text = text.lower().translate(str.maketrans("", "", string.punctuation))
        return {w for w in text.split() if w not in self.stop_words}
