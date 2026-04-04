import json
import os
import re
from dataclasses import dataclass
from typing import Any, Literal

import requests

SentimentLabel = Literal["positive", "neutral", "negative"]


@dataclass(frozen=True)
class SentimentResult:
    sentiment: SentimentLabel
    confidence: float
    raw: str


class ChatProvider:
    def chat(self, *, messages: list[dict[str, str]]) -> str:
        raise NotImplementedError


class OllamaChatProvider(ChatProvider):
    def __init__(
        self,
        *,
        base_url: str = "http://localhost:11434",
        model: str = "gemma3",
        timeout_s: float = 60.0,
    ):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout_s = timeout_s

    def chat(self, *, messages: list[dict[str, str]]) -> str:
        url = f"{self.base_url}/api/chat"
        payload = {"model": self.model, "messages": messages, "stream": False}
        try:
            r = requests.post(url, json=payload, timeout=self.timeout_s)
        except requests.exceptions.ConnectionError as e:
            raise RuntimeError(
                "Could not connect to Ollama. Make sure Ollama is running and reachable. "
                f"Tried: {url}. If Ollama is on a different host/port, pass --ollama-url."
            ) from e
        r.raise_for_status()
        data = r.json()
        message = data.get("message")
        if not isinstance(message, dict):
            raise ValueError("Invalid Ollama response: missing message")
        content = message.get("content")
        if not isinstance(content, str):
            raise ValueError("Invalid Ollama response: missing content")
        return content


class OpenRouterChatProvider(ChatProvider):
    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str = "moonshotai/kimi-k2:free",
        timeout_s: float = 60.0,
        site_url: str | None = None,
        site_name: str | None = None,
    ):
        self.api_key = api_key or os.getenv("OPENROUTER_API_KEY")
        if not self.api_key:
            raise ValueError("OPENROUTER_API_KEY environment variable not set")
        self.model = model
        self.timeout_s = timeout_s
        self.site_url = site_url if site_url is not None else os.getenv("SITE_URL", "")
        self.site_name = (
            site_name if site_name is not None else os.getenv("SITE_NAME", "trust-engine-v2")
        )

    def chat(self, *, messages: list[dict[str, str]]) -> str:
        url = "https://openrouter.ai/api/v1/chat/completions"
        r = requests.post(
            url=url,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "HTTP-Referer": self.site_url,
                "X-Title": self.site_name,
            },
            json={
                "model": self.model,
                "messages": messages,
                "temperature": 0.0,
                "top_p": 1.0,
                "max_tokens": 200,
            },
            timeout=self.timeout_s,
        )
        r.raise_for_status()
        data = r.json()
        choices = data.get("choices")
        if not isinstance(choices, list) or not choices:
            raise ValueError("Invalid OpenRouter response: missing choices")
        msg = choices[0].get("message") if isinstance(choices[0], dict) else None
        if not isinstance(msg, dict):
            raise ValueError("Invalid OpenRouter response: missing message")
        content = msg.get("content")
        if not isinstance(content, str):
            raise ValueError("Invalid OpenRouter response: missing content")
        return content


class SentimentAnalyzer:
    def __init__(self, *, provider: ChatProvider):
        self.provider = provider

    def analyze(self, text: str) -> SentimentResult:
        text = (text or "").strip()
        if not text:
            return SentimentResult(sentiment="neutral", confidence=0.0, raw="")

        messages = [
            {
                "role": "system",
                "content": (
                    "You are a strict sentiment classifier for short Spanish social media posts. "
                    "Return ONLY a JSON object with keys: sentiment and confidence. "
                    "sentiment must be one of: positive, neutral, negative. "
                    "confidence must be a number between 0 and 1."
                ),
            },
            {
                "role": "user",
                "content": (
                    "Classify the sentiment of this text. Return ONLY JSON.\n\n" f"TEXT:\n{text}"
                ),
            },
        ]

        raw = self.provider.chat(messages=messages)
        parsed = _extract_json_object(raw)

        sentiment = parsed.get("sentiment")
        confidence = parsed.get("confidence")

        if sentiment not in ("positive", "neutral", "negative"):
            raise ValueError(f"Invalid sentiment label: {sentiment!r}")
        try:
            confidence_f = float(confidence)
        except Exception as e:
            raise ValueError(f"Invalid confidence: {confidence!r}") from e

        if confidence_f < 0.0:
            confidence_f = 0.0
        if confidence_f > 1.0:
            confidence_f = 1.0

        return SentimentResult(sentiment=sentiment, confidence=confidence_f, raw=raw)


def _extract_json_object(raw: str) -> dict[str, Any]:
    raw = (raw or "").strip()
    if not raw:
        raise ValueError("Empty model response")

    try:
        obj = json.loads(raw)
        if isinstance(obj, dict):
            return obj
    except Exception:
        pass

    m = re.search(r"\{[\s\S]*\}", raw)
    if not m:
        raise ValueError("Model response did not contain a JSON object")

    candidate = m.group(0)
    obj = json.loads(candidate)
    if not isinstance(obj, dict):
        raise ValueError("Parsed JSON is not an object")
    return obj
