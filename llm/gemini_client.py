"""Small wrapper around the Google Gemini API."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from utils.config import config

DEFAULT_TIMEOUT_MS = 120_000
DEFAULT_TEMPERATURE = 0.2
DEFAULT_MAX_OUTPUT_TOKENS = 8192


class GeminiClientError(RuntimeError):
    pass


@dataclass
class GeminiResponse:
    model: str
    text: str
    raw: Any = None


class GeminiClient:
    """Gemini client using the installed google-genai package."""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str | None = None,
        timeout_ms: int = DEFAULT_TIMEOUT_MS,
    ):
        self.api_key = api_key if api_key is not None else config.GEMINI_API_KEY
        self.model = model or config.GEMINI_MODEL
        self.timeout_ms = timeout_ms

    def generate_json(
        self,
        *,
        system_instruction: str,
        user_content: str,
        model: str | None = None,
        temperature: float = DEFAULT_TEMPERATURE,
        max_output_tokens: int = DEFAULT_MAX_OUTPUT_TOKENS,
    ) -> GeminiResponse:
        if not self.api_key:
            raise GeminiClientError(
                "GEMINI_API_KEY is not configured. Set GEMINI_API_KEY or GOOGLE_API_KEY in .env."
            )

        try:
            from google import genai
            from google.genai import types
        except ImportError as exc:
            raise GeminiClientError("google-genai is not installed") from exc

        selected_model = model or self.model
        client = genai.Client(api_key=self.api_key)
        try:
            response = client.models.generate_content(
                model=selected_model,
                contents=user_content,
                config=types.GenerateContentConfig(
                    system_instruction=system_instruction,
                    temperature=temperature,
                    max_output_tokens=max_output_tokens,
                    response_mime_type="application/json",
                    http_options=types.HttpOptions(timeout=self.timeout_ms),
                ),
            )
        except Exception as exc:
            raise GeminiClientError(f"Gemini request failed for {selected_model}: {exc}") from exc

        text = getattr(response, "text", None)
        if not text:
            raise GeminiClientError(f"Gemini returned an empty response for {selected_model}")
        return GeminiResponse(model=selected_model, text=text, raw=response)

    def smoke_test(self, *, model: str | None = None) -> GeminiResponse:
        return self.generate_json(
            system_instruction="Return JSON only.",
            user_content='Return exactly this JSON object: {"ok": true}',
            model=model,
            temperature=0,
            max_output_tokens=64,
        )
