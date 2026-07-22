"""Offline integration tests for the OpenAI-compatible Hy3 client."""

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import BaseModel

from hy3_data_analyst_mcp.config import Settings
from hy3_data_analyst_mcp.errors import Hy3ResponseError
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
