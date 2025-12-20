import pytest

from trust_api.models import ArticleInput
from trust_api.services.metrics import (
    get_adjective_count,
    get_sentence_complexity,
    get_verb_tense_analysis,
    get_word_count,
)


class DummyWord:
    def __init__(self, text: str, upos: str, feats: str | None = None):
        self.text = text
        self.upos = upos
        self.feats = feats


class DummySentence:
    def __init__(self, words):
        self.words = words


class DummyDoc:
    def __init__(self, sentences):
        self.sentences = sentences


def test_article_input_validation():
    data = {
        "body": "Example body",
        "title": "Example title",
        "author": "Author",
        "link": "https://example.com",
        "date": "2025-10-04",
        "media_type": "news",
    }
    model = ArticleInput(**data)
    assert model.body == "Example body"
    assert model.media_type == "news"

    with pytest.raises(Exception):
        ArticleInput(**{k: v for k, v in data.items() if k != "body"})


def test_word_count_metric():
    sentences = [DummySentence([DummyWord("w", "NOUN") for _ in range(350)])]
    doc = DummyDoc(sentences)
    metric = get_word_count(doc, metric_id=2)
    assert metric.criteria_name == "Word Count"
    assert metric.flag == 0  # 350 words => adequate
    assert metric.score == pytest.approx(0.6)


def test_sentence_complexity_metric():
    sentences = [
        DummySentence([DummyWord("w", "NOUN") for _ in range(10)]),
        DummySentence([DummyWord("w", "NOUN") for _ in range(20)]),
    ]
    doc = DummyDoc(sentences)
    metric = get_sentence_complexity(doc, metric_id=3)
    assert metric.flag == 1
    assert "Average sentence length" in metric.explanation


def test_verb_tense_metric():
    sentences = [
        DummySentence(
            [
                DummyWord("ran", "VERB", "Tense=Past"),
                DummyWord("said", "VERB", "Tense=Past"),
                DummyWord("walk", "VERB", None),
                DummyWord("is", "VERB", "Tense=Pres"),
            ]
        )
    ]
    doc = DummyDoc(sentences)
    metric = get_verb_tense_analysis(doc, metric_id=4)
    assert metric.flag in (-1, 0, 1)
    assert "Past tense usage" in metric.explanation


def test_adjective_metric_without_llm(monkeypatch):
    # Ensure OpenRouter is not used
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    words = [DummyWord("good", "ADJ") for _ in range(10)] + [
        DummyWord("word", "NOUN") for _ in range(90)
    ]
    sentences = [DummySentence(words)]
    doc = DummyDoc(sentences)
    metric = get_adjective_count(doc, metric_id=1)
    assert metric.flag == 0  # 10% adjectives -> moderate
    assert "qualitative adjective ratio" in metric.explanation.lower()
