"""Tests for spec 08 – ConfidenceScorer."""
from __future__ import annotations

import pytest

from erks.subagent.confidence import ConfidenceScorer


@pytest.fixture
def scorer():
    return ConfidenceScorer()


# ---------------------------------------------------------------------------
# _preprocess
# ---------------------------------------------------------------------------


def test_preprocess_lowercases(scorer):
    result = scorer._preprocess("Hello World")
    assert "hello" in result
    assert "world" in result


def test_preprocess_removes_punctuation(scorer):
    result = scorer._preprocess("hello, world!")
    assert "hello" in result
    assert "world" in result
    assert "," not in "".join(result)


def test_preprocess_removes_stop_words(scorer):
    result = scorer._preprocess("the cat and the dog")
    assert "the" not in result
    assert "and" not in result
    assert "cat" in result
    assert "dog" in result


def test_preprocess_empty_string_returns_empty_set(scorer):
    assert scorer._preprocess("") == set()


def test_preprocess_only_stop_words_returns_empty_set(scorer):
    assert scorer._preprocess("the and is in") == set()


# ---------------------------------------------------------------------------
# score – basic calculations
# ---------------------------------------------------------------------------


def test_score_pure_vector_no_keyword_overlap(scorer):
    # No shared keywords → overlap = 0; result = vector_score * 0.7
    result = scorer.score("zzzz", "xxxx", 0.8)
    assert abs(result - 0.56) < 1e-6


def test_score_full_keyword_overlap_zero_vector(scorer):
    # All keywords present → overlap = 1.0; result = 0.3
    result = scorer.score("python code", "python code is great", 0.0)
    assert abs(result - 0.3) < 1e-6


def test_score_combined_weights():
    scorer = ConfidenceScorer(stop_words=set())
    # query: {"hello"}, chunk contains "hello" → overlap = 1.0
    # score = 0.6 * 0.7 + 1.0 * 0.3 = 0.42 + 0.30 = 0.72
    result = scorer.score("hello", "hello world", 0.6)
    assert abs(result - 0.72) < 1e-6


def test_score_clamped_to_zero_for_negative_vector():
    scorer = ConfidenceScorer(stop_words=set())
    # vector = -1.0, overlap = 0 → raw = -0.7 → clamped to 0.0
    result = scorer.score("foo", "bar", -1.0)
    assert result == 0.0


def test_score_clamped_to_one_for_high_values(scorer):
    # Even if vector_score > 1.0 somehow, clamped to 1.0
    result = scorer.score("alpha beta gamma", "alpha beta gamma", 1.5)
    assert result == 1.0


def test_score_empty_query_zero_overlap(scorer):
    # Query is all stop words → query_kw empty → overlap = 0
    result = scorer.score("the and is", "some chunk text", 0.5)
    assert abs(result - 0.5 * 0.7) < 1e-6


def test_score_deterministic(scorer):
    s1 = scorer.score("machine learning", "deep learning models", 0.75)
    s2 = scorer.score("machine learning", "deep learning models", 0.75)
    assert s1 == s2


def test_score_is_between_zero_and_one(scorer):
    for vs in [-0.5, 0.0, 0.5, 1.0, 1.5]:
        s = scorer.score("test query", "some relevant text", vs)
        assert 0.0 <= s <= 1.0


# ---------------------------------------------------------------------------
# Custom stop words
# ---------------------------------------------------------------------------


def test_custom_stop_words():
    scorer = ConfidenceScorer(stop_words={"foo"})
    result = scorer._preprocess("foo bar baz")
    assert "foo" not in result
    assert "bar" in result


def test_empty_stop_words():
    scorer = ConfidenceScorer(stop_words=set())
    result = scorer._preprocess("the and is")
    assert result == {"the", "and", "is"}


# ---------------------------------------------------------------------------
# Partial keyword overlap
# ---------------------------------------------------------------------------


def test_score_partial_overlap():
    scorer = ConfidenceScorer(stop_words=set())
    # query keywords: {"python", "code"}, chunk has "python" but not "code"
    # overlap = 1/2 = 0.5
    result = scorer.score("python code", "python examples", 0.0)
    assert abs(result - 0.15) < 1e-6  # 0.0 * 0.7 + 0.5 * 0.3 = 0.15
