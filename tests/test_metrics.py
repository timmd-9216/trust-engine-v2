"""Tests for metric calculation functions."""

from unittest.mock import MagicMock, patch

import requests

from trust_api.models import Metric
from trust_api.services.metrics import (
    get_adjective_count,
    get_sentence_complexity,
    get_verb_tense_analysis,
    get_word_count,
)


class TestGetAdjectiveCount:
    """Tests for get_adjective_count function."""

    def test_no_adjectives(self, mock_stanza_doc):
        """Test when no adjectives are found."""
        # Remove adjectives from mock
        for sentence in mock_stanza_doc.sentences:
            sentence.words = [w for w in sentence.words if w.upos != "ADJ"]

        result = get_adjective_count(mock_stanza_doc, metric_id=0)
        assert isinstance(result, Metric)
        assert result.id == 0
        assert result.criteria_name == "Qualitative Adjectives"
        assert result.flag == 1
        assert result.score == 1.0

    def test_adjectives_without_api_key(self, mock_stanza_doc, monkeypatch):
        """Test adjective counting without OpenRouter API key."""
        monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)

        result = get_adjective_count(mock_stanza_doc, metric_id=0)
        assert isinstance(result, Metric)
        assert result.id == 0
        assert "Qualitative Adjectives" in result.criteria_name

    @patch("trust_api.services.metrics.OpenRouterLM")
    @patch("trust_api.services.metrics.dspy")
    def test_adjectives_with_api_key(
        self, mock_dspy, mock_openrouter_lm, mock_stanza_doc, monkeypatch
    ):
        """Test adjective counting with OpenRouter API key."""
        monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")

        # Mock DSPy context and module
        mock_context = MagicMock()
        mock_dspy.context.return_value.__enter__ = MagicMock(return_value=mock_context)
        mock_dspy.context.return_value.__exit__ = MagicMock(return_value=None)

        mock_module = MagicMock()
        mock_result = MagicMock()
        mock_result.count = "2"
        mock_module.return_value = mock_result
        mock_dspy.ChainOfThought.return_value = mock_module

        result = get_adjective_count(mock_stanza_doc, metric_id=0)
        assert isinstance(result, Metric)
        assert result.id == 0

    @patch("trust_api.services.metrics.requests.post")
    def test_adjectives_api_failure(self, mock_post, mock_stanza_doc, monkeypatch):
        """Test fallback when OpenRouter API fails."""
        monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")

        # Mock API failure
        mock_post.side_effect = requests.RequestException("API Error")

        result = get_adjective_count(mock_stanza_doc, metric_id=0)
        assert isinstance(result, Metric)
        # Should still return a valid metric despite API failure


class TestGetWordCount:
    """Tests for get_word_count function."""

    def test_word_count_high(self, mock_stanza_doc):
        """Test word count metric for long articles."""
        # Create a document with many words
        long_sentence = MagicMock()
        long_sentence.words = [MagicMock()] * 500
        mock_stanza_doc.sentences = [long_sentence]

        result = get_word_count(mock_stanza_doc, metric_id=1)
        assert isinstance(result, Metric)
        assert result.id == 1
        assert result.criteria_name == "Word Count"
        assert result.flag == 1
        assert result.score == 0.9

    def test_word_count_medium(self, mock_stanza_doc):
        """Test word count metric for medium articles."""
        medium_sentence = MagicMock()
        medium_sentence.words = [MagicMock()] * 350
        mock_stanza_doc.sentences = [medium_sentence]

        result = get_word_count(mock_stanza_doc, metric_id=1)
        assert isinstance(result, Metric)
        assert result.flag == 0
        assert result.score == 0.6

    def test_word_count_low(self, mock_stanza_doc):
        """Test word count metric for short articles."""
        short_sentence = MagicMock()
        short_sentence.words = [MagicMock()] * 200
        mock_stanza_doc.sentences = [short_sentence]

        result = get_word_count(mock_stanza_doc, metric_id=1)
        assert isinstance(result, Metric)
        assert result.flag == -1
        assert result.score == 0.3


class TestGetSentenceComplexity:
    """Tests for get_sentence_complexity function."""

    def test_no_sentences(self):
        """Test when no sentences are found."""
        empty_doc = MagicMock()
        empty_doc.sentences = []

        result = get_sentence_complexity(empty_doc, metric_id=2)
        assert isinstance(result, Metric)
        assert result.id == 2
        assert result.criteria_name == "Sentence Complexity"
        assert result.flag == -1
        assert result.score == 0.0

    def test_optimal_sentence_length(self, mock_stanza_doc):
        """Test sentence complexity with optimal length."""
        # Create sentences with ~20 words each (optimal range)
        optimal_sentence = MagicMock()
        optimal_sentence.words = [MagicMock()] * 20
        mock_stanza_doc.sentences = [optimal_sentence] * 5

        result = get_sentence_complexity(mock_stanza_doc, metric_id=2)
        assert isinstance(result, Metric)
        assert result.flag == 1
        assert result.score == 0.9

    def test_short_sentences(self, mock_stanza_doc):
        """Test sentence complexity with short sentences."""
        short_sentence = MagicMock()
        short_sentence.words = [MagicMock()] * 5
        mock_stanza_doc.sentences = [short_sentence] * 3

        result = get_sentence_complexity(mock_stanza_doc, metric_id=2)
        assert isinstance(result, Metric)
        assert result.flag == -1
        assert result.score == 0.3

    def test_long_sentences(self, mock_stanza_doc):
        """Test sentence complexity with long sentences."""
        long_sentence = MagicMock()
        long_sentence.words = [MagicMock()] * 40
        mock_stanza_doc.sentences = [long_sentence] * 2

        result = get_sentence_complexity(mock_stanza_doc, metric_id=2)
        assert isinstance(result, Metric)
        assert result.flag == -1
        assert result.score == 0.3


class TestGetVerbTenseAnalysis:
    """Tests for get_verb_tense_analysis function."""

    def test_no_verbs(self):
        """Test when no verbs are found."""
        empty_doc = MagicMock()
        empty_doc.sentences = []
        sentence = MagicMock()
        sentence.words = []
        empty_doc.sentences = [sentence]

        result = get_verb_tense_analysis(empty_doc, metric_id=3)
        assert isinstance(result, Metric)
        assert result.id == 3
        assert result.criteria_name == "Verb Tense"
        assert result.flag == -1
        assert result.score == 0.0

    def test_optimal_past_tense_ratio(self, mock_stanza_doc):
        """Test verb tense analysis with optimal past tense ratio."""
        # Create verbs with ~50% past tense (optimal range: 40-70%)
        sentence = MagicMock()
        verb1 = MagicMock()
        verb1.upos = "VERB"
        verb1.feats = "Tense=Past"
        verb2 = MagicMock()
        verb2.upos = "VERB"
        verb2.feats = "Tense=Pres"
        sentence.words = [verb1, verb2]
        mock_stanza_doc.sentences = [sentence] * 5

        result = get_verb_tense_analysis(mock_stanza_doc, metric_id=3)
        assert isinstance(result, Metric)
        assert result.flag == 1
        assert result.score == 0.85

    def test_low_past_tense_ratio(self, mock_stanza_doc):
        """Test verb tense analysis with low past tense ratio."""
        sentence = MagicMock()
        verb1 = MagicMock()
        verb1.upos = "VERB"
        verb1.feats = "Tense=Pres"
        verb2 = MagicMock()
        verb2.upos = "VERB"
        verb2.feats = "Tense=Pres"
        verb3 = MagicMock()
        verb3.upos = "VERB"
        verb3.feats = "Tense=Past"
        sentence.words = [verb1, verb2, verb3]
        mock_stanza_doc.sentences = [sentence] * 3

        result = get_verb_tense_analysis(mock_stanza_doc, metric_id=3)
        assert isinstance(result, Metric)
        # Should have low past tense ratio (< 40%)
        assert result.flag in [-1, 0]

    def test_high_past_tense_ratio(self, mock_stanza_doc):
        """Test verb tense analysis with high past tense ratio."""
        sentence = MagicMock()
        verb1 = MagicMock()
        verb1.upos = "VERB"
        verb1.feats = "Tense=Past"
        verb2 = MagicMock()
        verb2.upos = "VERB"
        verb2.feats = "Tense=Past"
        sentence.words = [verb1, verb2]
        mock_stanza_doc.sentences = [sentence] * 5

        result = get_verb_tense_analysis(mock_stanza_doc, metric_id=3)
        assert isinstance(result, Metric)
        # Should have high past tense ratio (> 70%)
        assert result.flag in [-1, 0]
