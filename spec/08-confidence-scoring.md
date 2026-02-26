# Confidence Scoring Spec

## Purpose
Score answers using cosine similarity and keyword presence.

## Requirements
- Compute cosine similarity between query and chunk embeddings.
- Detect keyword overlap between query and chunk.
- Combine scores (e.g., weighted sum).
- Return float confidence per answer.

## Success Criteria
- Confidence scores calibrated (0.0–1.0).
- Formula documented and testable.
- Scores correlate with answer relevance.
