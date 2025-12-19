"""Services module for MediaParty Trust API."""

from trust_api.services.metrics import (
    get_adjective_count,
    get_sentence_complexity,
    get_verb_tense_analysis,
    get_word_count,
)
from trust_api.services.stanza_service import stanza_service

__all__ = [
    "stanza_service",
    "get_adjective_count",
    "get_word_count",
    "get_sentence_complexity",
    "get_verb_tense_analysis",
]
