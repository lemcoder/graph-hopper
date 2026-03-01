# Confidence Scoring Spec

## Purpose
Define a standalone component to compute a hybrid confidence score for retrieved answers (or chunks) against a user's query. The score combines semantic vector similarity with lexical keyword overlap to provide a calibrated relevance metric.

## Key Decisions

1. **Separate Architecture:** The scoring logic is encapsulated in a dedicated `ConfidenceScorer` class, decoupling it from the `Retriever` and `VectorStore`.
2. **Reuse Vector Scores:** Instead of recomputing embeddings, the scorer accepts the `distance` score (which represents cosine similarity, given the L2-normalization in the FAISS index) directly from the `VectorStore`'s search results.
3. **Keyword Overlap Logic:** 
   - Both the query and the answer text are preprocessed: lowercased, stripped of punctuation, and filtered of common stop words (e.g., "the", "and", "is").
   - The overlap is calculated as the proportion of processed query keywords that appear in the processed answer text.
4. **Weighted Combination:** The final confidence score is a weighted sum: **70% Cosine Similarity** and **30% Keyword Overlap**.
5. **Per Answer Scoring:** The score is calculated individually per answer/chunk evaluated.

## Architecture & Data Flow

### 1. Preprocessing
- A text normalization utility lowercases the input strings and removes all punctuation.
- The strings are split into tokens (words).
- A predefined list of common English stop words is filtered out of both the query tokens and the answer tokens.

### 2. Keyword Overlap Calculation
- Calculate the set of unique `query_keywords`.
- Calculate the set of unique `answer_keywords`.
- Find the intersection.
- `overlap_score = len(intersection) / len(query_keywords)` (if `query_keywords` is empty, `overlap_score` defaults to `0.0`).

### 3. Final Score Computation
- `final_score = (vector_score * 0.7) + (overlap_score * 0.3)`
- The final score is clamped between `0.0` and `1.0` to ensure safe downstream consumption.

## Interface Definition

```python
import string

class ConfidenceScorer:
    def __init__(self, stop_words: set[str] = None):
        if stop_words is None:
            # Basic default set; can be expanded or injected
            self.stop_words = {"the", "and", "is", "in", "it", "of", "to", "a", "for", "on", "with"}
        else:
            self.stop_words = stop_words

    def _preprocess(self, text: str) -> set[str]:
        """Lowercases, strips punctuation, and removes stop words."""
        text = text.lower()
        text = text.translate(str.maketrans('', '', string.punctuation))
        tokens = text.split()
        return {word for word in tokens if word not in self.stop_words}

    def score(self, query: str, answer_text: str, vector_score: float) -> float:
        """
        Calculates a hybrid confidence score (0.0 to 1.0) using 
        70% vector similarity and 30% keyword overlap.
        """
        query_keywords = self._preprocess(query)
        answer_keywords = self._preprocess(answer_text)

        if not query_keywords:
            overlap_score = 0.0
        else:
            intersection = query_keywords.intersection(answer_keywords)
            overlap_score = len(intersection) / len(query_keywords)

        # Weighted combination
        final_score = (vector_score * 0.7) + (overlap_score * 0.3)
        
        # Ensure the score is within [0.0, 1.0] bounds
        return max(0.0, min(1.0, final_score))
```

## Success Criteria
- **Calibration:** Confidence scores are strictly bounded between `0.0` and `1.0`.
- **Determinism:** The same query, answer, and vector score always yield the exact same confidence score.
- **Robustness:** Edge cases (e.g., query contains only stop words or punctuation) are handled gracefully without division-by-zero errors.
- **Testability:** The formula and text preprocessing steps are fully unit-testable in isolation.