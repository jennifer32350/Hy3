"""Async OpenAI-compatible Hy3 client with safe error mapping."""

from __future__ import annotations

import asyncio
import json
from typing import Any, TypeVar

import openai
from openai import AsyncOpenAI
from pydantic import BaseModel, ValidationError

from hy3_data_analyst_mcp.config import Settings
from hy3_data_analyst_mcp.errors import (
    Hy3APIError,
    Hy3AuthenticationError,
    Hy3RateLimitError,
    Hy3ResponseError,
    Hy3StructuredOutputError,
    Hy3TimeoutError,
)

ModelT = TypeVar("ModelT", bound=BaseModel)
HY3_MAX_OUTPUT_TOKENS = 16_384
HY3_TEXT_TEMPERATURE = 0.9
HY3_STRUCTURED_TEMPERATURE = 0.2
# Backward-compatible name for callers that configured/asserted plain-text requests.
HY3_TEMPERATURE = HY3_TEXT_TEMPERATURE
HY3_TOP_P = 1.0


class Hy3Client:
    """Make bounded non-streaming requests to an OpenAI-compatible Hy3 endpoint."""

    def __init__(self, settings: Settings, *, client: Any | None = None) -> None:
        self._settings = settings
        self._client = client

    def _get_client(self) -> Any:
        if self._client is None:
            self._client = AsyncOpenAI(
                api_key=self._settings.require_api_key(),
                base_url=self._settings.base_url,
                timeout=self._settings.timeout_seconds,
                max_retries=0,
            )
        return self._client

    async def complete(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        reasoning_effort: str | None = None,
    ) -> str:
        """Return non-empty response text from Hy3."""
        response = await self._request(
            {
                "model": self._settings.model_name,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                "stream": False,
                "max_tokens": HY3_MAX_OUTPUT_TOKENS,
                "temperature": HY3_TEXT_TEMPERATURE,
                "top_p": HY3_TOP_P,
                "extra_body": {
                    "chat_template_kwargs": {
                        "reasoning_effort": _hy3_reasoning_effort(
                            reasoning_effort or self._settings.reasoning_effort
                        )
                    }
                },
            }
        )
        try:
            content = response.choices[0].message.content
        except (AttributeError, IndexError, TypeError) as exc:
            raise Hy3ResponseError(
                "Hy3 returned a response without message content.",
                "Retry the request or check that the endpoint is OpenAI-compatible.",
            ) from exc
        if not isinstance(content, str) or not content.strip():
            raise Hy3ResponseError(
                "Hy3 returned empty message content.",
                "Retry the request or check the configured model endpoint.",
            )
        return content.strip()

    async def complete_structured(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        response_model: type[ModelT],
        reasoning_effort: str | None = None,
    ) -> ModelT:
        """Request JSON Schema output and validate it with Pydantic."""
        response = await self._request(
            {
                "model": self._settings.model_name,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                "stream": False,
                "max_tokens": HY3_MAX_OUTPUT_TOKENS,
                "temperature": HY3_STRUCTURED_TEMPERATURE,
                "top_p": HY3_TOP_P,
                "extra_body": {
                    "chat_template_kwargs": {
                        "reasoning_effort": _hy3_reasoning_effort(
                            reasoning_effort or self._settings.reasoning_effort
                        )
                    }
                },
                "response_format": {
                    "type": "json_schema",
                    "json_schema": {
                        "name": response_model.__name__,
                        "strict": True,
                        "schema": response_model.model_json_schema(),
                    },
                },
            }
        )
        try:
            content = response.choices[0].message.content
        except (AttributeError, IndexError, TypeError) as exc:
            raise Hy3StructuredOutputError(
                "Hy3 returned structured output without message content.",
                "Retry the request or verify endpoint JSON Schema support.",
                validation_details=["response.choices[0].message.content is missing"],
            ) from exc
        if not isinstance(content, str) or not content.strip():
            raise Hy3StructuredOutputError(
                "Hy3 returned empty structured output.",
                "Retry the request or verify endpoint JSON Schema support.",
                validation_details=["message content must be a non-empty JSON string"],
            )
        try:
            payload = json.loads(content)
        except json.JSONDecodeError as exc:
            raise Hy3StructuredOutputError(
                "Hy3 returned invalid JSON structured output.",
                "Repair the JSON syntax and return only schema-valid JSON.",
                validation_details=[
                    f"JSON syntax error at line {exc.lineno}, column {exc.colno}: {exc.msg}"
                ],
                invalid_payload=content[:8_000],
            ) from exc
        try:
            return response_model.model_validate(payload)
        except ValidationError as exc:
            details = [
                f"{'.'.join(str(part) for part in issue['loc'])}: {issue['msg']}"
                for issue in exc.errors(include_url=False)[:10]
            ]
            raise Hy3StructuredOutputError(
                "Hy3 returned structured output JSON that does not match the required schema.",
                "Correct the listed fields and return only schema-valid JSON.",
                validation_details=details,
                invalid_payload=payload,
            ) from exc

    async def _request(self, payload: dict[str, Any]) -> Any:
        attempts = self._settings.max_retries + 1
        for attempt in range(attempts):
            try:
                return await self._get_client().chat.completions.create(**payload)
            except (openai.AuthenticationError, openai.PermissionDeniedError) as exc:
                raise Hy3AuthenticationError(
                    "Hy3 rejected the configured credentials.",
                    "Check HY3_API_KEY and endpoint access, then retry.",
                ) from exc
            except openai.APITimeoutError as exc:
                if attempt + 1 < attempts:
                    await asyncio.sleep(0)
                    continue
                raise Hy3TimeoutError(
                    "The Hy3 request timed out.",
                    "Retry later or increase HY3_TIMEOUT_SECONDS intentionally.",
                ) from exc
            except openai.RateLimitError as exc:
                if attempt + 1 < attempts:
                    await asyncio.sleep(0)
                    continue
                raise Hy3RateLimitError(
                    "The Hy3 endpoint rate limit was exceeded.",
                    "Wait briefly and retry the request.",
                ) from exc
            except (openai.APIConnectionError, openai.InternalServerError) as exc:
                if attempt + 1 < attempts:
                    await asyncio.sleep(0)
                    continue
                raise Hy3APIError(
                    "The Hy3 endpoint is temporarily unavailable.",
                    "Check HY3_BASE_URL and network access, then retry.",
                ) from exc
            except openai.APIError as exc:
                raise Hy3APIError(
                    "The Hy3 request failed.",
                    "Check the endpoint configuration and retry.",
                ) from exc
        raise AssertionError("retry loop exited unexpectedly")


def _hy3_reasoning_effort(value: str) -> str:
    """Translate the public low/high setting to Hy3 chat-template values."""
    return "no_think" if value == "low" else "high"
