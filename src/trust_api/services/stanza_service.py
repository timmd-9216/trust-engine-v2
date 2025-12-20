"""Stanza NLP service for Spanish text analysis."""

import os

import stanza
from stanza import Document


class StanzaService:
    """
    Service for handling Stanza NLP operations.

    This service manages the Stanza Spanish language model and provides
    methods for text analysis.
    """

    def __init__(self):
        """Initialize the StanzaService with no model loaded."""
        self._nlp = None

    def initialize(self):
        """
        Initialize the Spanish Stanza model.

        This method downloads the Spanish model if not present and loads it.
        Should be called during application startup.
        """
        resources_dir = os.getenv("STANZA_RESOURCES_DIR") or os.path.join(
            os.getcwd(), "stanza_resources"
        )
        lang = os.getenv("STANZA_LANG", "es")

        # Download Spanish model if not already downloaded
        stanza.download(lang, verbose=True, model_dir=resources_dir)

        # Initialize the Spanish pipeline with common processors
        self._nlp = stanza.Pipeline(
            lang=lang,
            processors="tokenize,mwt,pos,lemma,depparse",
            verbose=False,
            dir=resources_dir,
        )

    def create_doc(self, text: str) -> Document:
        """
        Create a Stanza Document from input text.

        Args:
            text: Input text to process

        Returns:
            Stanza Document object with linguistic annotations

        Raises:
            RuntimeError: If the model hasn't been initialized
        """
        if self._nlp is None:
            raise RuntimeError("Stanza model not initialized. Call initialize() first.")

        return self._nlp(text)

    @property
    def is_initialized(self) -> bool:
        """Check if the Stanza model is initialized."""
        return self._nlp is not None


# Global instance to be used across the application
stanza_service = StanzaService()
