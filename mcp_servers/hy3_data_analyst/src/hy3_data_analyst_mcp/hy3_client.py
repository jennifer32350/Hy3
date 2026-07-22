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
    Hy3TimeoutError,
)

ModelT = TypeVar("ModelT", bound=BaseModel)


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
                "reasoning_effort": reasoning_effort or self._settings.reasoning_effort,
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
                "reasoning_effort": reasoning_effort or self._settings.reasoning_effort,
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
            payload = json.loads(content)
            return response_model.model_validate(payload)
        except (
            AttributeError,
            IndexError,
            TypeError,
            json.JSONDecodeError,
            ValidationError,
        ) as exc:
            raise Hy3ResponseError(
                "Hy3 returned invalid structured output.",
                "Retry the request; if it persists, verify endpoint JSON Schema support.",
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
