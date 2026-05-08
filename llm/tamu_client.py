import json
from dataclasses import dataclass
from typing import Any

import requests

from utils.config import config

DEFAULT_TIMEOUT_SEC = 90
DEFAULT_TEMPERATURE = 0.2
DEFAULT_MAX_TOKENS = 4500

TAMU_AVAILABLE_MODELS = [
    "protected.o3",
    "protected.Claude Opus 4.1",
    "protected.Claude Opus 4.6",
    "protected.Claude 3.5 Haiku",
    "protected.Claude-Haiku-4.5",
    "protected.Claude Sonnet 4.6",
    "protected.gpt-5.4-nano",
    "protected.Claude Opus 4.5",
    "protected.gemini-2.0-flash",
    "protected.Claude Sonnet 4.5",
    "protected.gpt-5-nano",
    "protected.gemini-2.0-flash-lite",
    "protected.gemini-2.5-pro",
    "protected.text-embedding-3-small",
    "protected.o4-mini",
    "protected.gemini-2.5-flash-lite",
    "protected.Claude Sonnet 4",
    "protected.gpt-4o",
    "protected.gpt-4.1",
    "protected.o3-mini",
    "protected.gpt-5-mini",
    "protected.gemini-2.5-flash",
    "protected.llama3.2",
    "protected.gpt-5",
    "protected.gpt-5.1",
    "protected.gpt-4.1-mini",
    "protected.gpt-4.1-nano",
    "protected.gpt-5.4",
    "protected.gpt-5.4-mini",
    "protected.gpt-5.2",
]

TAMU_TESTED_CHAT_MODELS = [
    model for model in TAMU_AVAILABLE_MODELS if model != "protected.text-embedding-3-small"
]


class TamuChatError(RuntimeError):
    pass


@dataclass
class TamuModelResult:
    model: str
    ok: bool
    response: str = ""
    error: str = ""


class TamuChatClient:
    """OpenAI-compatible client for TAMU chat completions.

    Supports both normal JSON responses and TAMU's text/event-stream responses.
    """

    def __init__(
        self,
        *,
        api_key: str | None = None,
        endpoint: str | None = None,
        model: str | None = None,
        fallbacks: list[str] | None = None,
        timeout_sec: int = DEFAULT_TIMEOUT_SEC,
    ):
        self.api_key = api_key if api_key is not None else config.TAMU_API_KEY
        self.endpoint = endpoint or config.TAMU_API_ENDPOINT
        self.model = model or config.TAMU_MODEL
        self.fallbacks = fallbacks if fallbacks is not None else config.TAMU_MODEL_FALLBACKS
        self.timeout_sec = timeout_sec

    def complete(
        self,
        messages: list[dict[str, str]],
        *,
        model: str | None = None,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        temperature: float = DEFAULT_TEMPERATURE,
    ) -> str:
        if not self.api_key:
            raise TamuChatError("TAMU_API_KEY is not configured")

        if model is None:
            errors = []
            for candidate in self.model_candidates():
                try:
                    return self.complete(
                        messages,
                        model=candidate,
                        max_tokens=max_tokens,
                        temperature=temperature,
                    )
                except Exception as exc:
                    errors.append(f"{candidate}: {exc}")
            raise TamuChatError("all TAMU model candidates failed: " + " | ".join(errors))

        request_temperature = normalize_temperature(model, temperature)
        response = requests.post(
            self.endpoint,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": model,
                "messages": messages,
                "temperature": request_temperature,
                "max_tokens": max_tokens,
            },
            timeout=self.timeout_sec,
        )
        if response.status_code >= 400:
            raise TamuChatError(
                f"TAMU request failed for {model}: {response.status_code} {response.text[:500]}"
            )

        content_type = response.headers.get("content-type", "")
        if "text/event-stream" in content_type:
            content = parse_sse_chat_response(response.text)
            raise_if_tamu_error_text(model, content)
            return content

        data = response.json()
        try:
            content = data["choices"][0]["message"]["content"]
            raise_if_tamu_error_text(model, content)
            return content
        except (KeyError, IndexError, TypeError) as exc:
            raise TamuChatError(f"unexpected TAMU response shape: {data}") from exc

    def test_models(self) -> list[TamuModelResult]:
        results = []
        for model in self.model_candidates():
            try:
                response = self.complete(
                    [
                        {
                            "role": "system",
                            "content": "You are a connection test. Reply with exactly OK.",
                        },
                        {"role": "user", "content": "Reply OK."},
                    ],
                    model=model,
                    max_tokens=16,
                    temperature=0,
                )
                results.append(TamuModelResult(model=model, ok=True, response=response.strip()))
            except Exception as exc:
                results.append(TamuModelResult(model=model, ok=False, error=str(exc)))
        return results

    def list_models(self) -> list[dict[str, Any]]:
        """Return available models via the tamu-chat package when installed."""
        try:
            from tamu_chat import TAMUChatClient as PackageTamuChatClient
        except ImportError as exc:
            raise TamuChatError("tamu-chat package is not installed") from exc

        package_client = PackageTamuChatClient(
            api_key=self.api_key,
            base_url=self.endpoint.removesuffix("/chat/completions"),
        )
        return package_client.list_models()

    def model_candidates(self) -> list[str]:
        seen = set()
        models = []
        for model in [self.model, *self.fallbacks]:
            if model and model not in seen:
                seen.add(model)
                models.append(model)
        return models


def parse_sse_chat_response(text: str) -> str:
    chunks = []
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("data:"):
            continue
        raw = line.removeprefix("data:").strip()
        if not raw or raw == "[DONE]":
            continue
        try:
            data: dict[str, Any] = json.loads(raw)
        except json.JSONDecodeError:
            continue
        for choice in data.get("choices", []):
            delta = choice.get("delta") or {}
            message = choice.get("message") or {}
            content = delta.get("content") or message.get("content")
            if content:
                chunks.append(content)
    if not chunks:
        raise TamuChatError("empty TAMU event-stream response")
    return "".join(chunks)


def normalize_temperature(model: str, temperature: float) -> float:
    if "claude" in model.lower():
        return 1
    return temperature


def raise_if_tamu_error_text(model: str, content: str) -> None:
    lowered = content.lower()
    if "unexpected error" in lowered or "litellm." in lowered or "error code:" in lowered:
        raise TamuChatError(f"TAMU returned an error message for {model}: {content[:500]}")
