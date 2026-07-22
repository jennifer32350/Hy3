"""Offline integration tests for the OpenAI-compatible Hy3 client."""

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import openai
import pytest
from pydantic import BaseModel

from hy3_data_analyst_mcp.config import Settings
from hy3_data_analyst_mcp.errors import (
    Hy3APIError,
    Hy3AuthenticationError,
    Hy3RateLimitError,
    Hy3ResponseError,
    Hy3TimeoutError,
)
from hy3_data_analyst_mcp.hy3_client import Hy3Client


class Answer(BaseModel):
    value: int


class FakeCompletions:
    def __init__(self, responses: list[Any]) -> None:
        self.responses = responses
        self.calls: list[dict[str, Any]] = []

    async def create(self, **payload: Any) -> Any:
        self.calls.append(payload)
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def _response(content: str | None) -> Any:
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])


def _client(fixture_dir: Path, responses: list[Any]) -> tuple[Hy3Client, FakeCompletions]:
    completions = FakeCompletions(responses)
    sdk = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    settings = Settings(data_dir=fixture_dir, api_key="test-placeholder")
    return Hy3Client(settings, client=sdk), completions


async def test_plain_completion_is_non_streaming(fixture_dir: Path) -> None:
    client, completions = _client(fixture_dir, [_response(" result ")])

    result = await client.complete(system_prompt="system", user_prompt="user")

    assert result == "result"
    assert completions.calls[0]["stream"] is False
    assert completions.calls[0]["model"] == "hy3"


async def test_structured_completion_validates_schema(fixture_dir: Path) -> None:
    client, completions = _client(fixture_dir, [_response('{"value": 7}')])

    result = await client.complete_structured(
        system_prompt="system", user_prompt="user", response_model=Answer
    )

    assert result == Answer(value=7)
    assert completions.calls[0]["response_format"]["type"] == "json_schema"


@pytest.mark.parametrize("content", [None, "", "not-json", '{"value":"bad"}'])
async def test_empty_or_invalid_output_is_mapped(fixture_dir: Path, content: str | None) -> None:
    client, _ = _client(fixture_dir, [_response(content)])

    if content in {None, ""}:
        with pytest.raises(Hy3ResponseError):
            await client.complete(system_prompt="system", user_prompt="user")
    else:
        with pytest.raises(Hy3ResponseError, match="structured output"):
            await client.complete_structured(
                system_prompt="system", user_prompt="user", response_model=Answer
            )


def _request() -> httpx.Request:
    return httpx.Request("POST", "https://example.invalid/v1/chat/completions")


def _status_error(error_type: type[openai.APIStatusError], status: int) -> openai.APIStatusError:
    response = httpx.Response(status, request=_request())
    return error_type("request failed", response=response, body=None)


@pytest.mark.parametrize(
    ("sdk_error", "project_error"),
    [
        (_status_error(openai.AuthenticationError, 401), Hy3AuthenticationError),
        (_status_error(openai.PermissionDeniedError, 403), Hy3AuthenticationError),
        (_status_error(openai.RateLimitError, 429), Hy3RateLimitError),
        (_status_error(openai.InternalServerError, 500), Hy3APIError),
        (openai.APITimeoutError(_request()), Hy3TimeoutError),
        (openai.APIConnectionError(request=_request()), Hy3APIError),
    ],
)
async def test_sdk_errors_are_mapped_after_bounded_retries(
    fixture_dir: Path,
    sdk_error: Exception,
    project_error: type[Exception],
) -> None:
    client, completions = _client(fixture_dir, [sdk_error, sdk_error, sdk_error])

    with pytest.raises(project_error):
        await client.complete(system_prompt="system", user_prompt="user")

    expected_attempts = (
        1
        if isinstance(sdk_error, (openai.AuthenticationError, openai.PermissionDeniedError))
        else 3
    )
    assert len(completions.calls) == expected_attempts


async def test_retry_can_recover_from_transient_failure(fixture_dir: Path) -> None:
    transient = openai.APIConnectionError(request=_request())
    client, completions = _client(fixture_dir, [transient, _response("recovered")])

    result = await client.complete(system_prompt="system", user_prompt="user")

    assert result == "recovered"
    assert len(completions.calls) == 2


async def test_other_sdk_api_error_is_safely_mapped(fixture_dir: Path) -> None:
    client, _ = _client(
        fixture_dir,
        [_status_error(openai.BadRequestError, 400)],
    )

    with pytest.raises(Hy3APIError, match="request failed"):
        await client.complete(system_prompt="system", user_prompt="user")


@pytest.mark.live
async def test_live_tokenhub_completion(fixture_dir: Path) -> None:
    """Optional smoke test: set HY3_RUN_LIVE_TESTS=1 and HY3_API_KEY to opt in."""
    import os

    if os.environ.get("HY3_RUN_LIVE_TESTS") != "1" or not os.environ.get("HY3_API_KEY"):
        pytest.skip("live TokenHub test requires explicit opt-in and HY3_API_KEY")
    settings = Settings(data_dir=fixture_dir, api_key=os.environ["HY3_API_KEY"])
    result = await Hy3Client(settings).complete(
        system_prompt="Reply concisely.",
        user_prompt="Reply with exactly: ok",
        reasoning_effort="low",
    )
    assert result
