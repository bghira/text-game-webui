"""Test that ZorkToolAwareLLM retries on empty LLM responses."""
from __future__ import annotations

import asyncio
import importlib.util
import json
from unittest.mock import MagicMock

import pytest

_HAS_TGE = importlib.util.find_spec("text_game_engine") is not None


def _make_llm(completion_port, delay=0.01):
    """Build a ZorkToolAwareLLM with a stub emulator for parse-only use."""
    from app.services.tge_gateway import ZorkToolAwareLLM

    llm = ZorkToolAwareLLM(
        session_factory=MagicMock(),
        completion_port=completion_port,
        temperature=0.7,
        max_tokens=2048,
    )
    llm._EMPTY_RESPONSE_DELAY = delay

    # Stub emulator with just enough for _parse_model_payload and post-parse checks
    stub = MagicMock()
    stub._clean_response = lambda text: text
    stub._extract_json = lambda text: text
    stub._parse_json_lenient = lambda text: json.loads(text)
    stub._is_tool_call = lambda payload: False
    llm._emulator = stub
    # Prevent post-parse validation paths from making extra LLM calls
    llm._should_force_auto_memory_search = lambda action: False
    llm._is_emptyish_payload = lambda payload: False
    llm._narration_has_explicit_clock_time = lambda narration: False
    llm._looks_like_major_narrative_beat = lambda payload: False
    return llm


@pytest.mark.skipif(not _HAS_TGE, reason="text_game_engine not installed")
def test_retries_on_empty_then_succeeds():
    """Empty responses trigger retries; a valid response on retry is returned."""
    call_count = 0
    responses = [None, None, '{"narration": "You look around the room."}']

    class FakePort:
        async def complete(self, system_prompt, prompt, *, temperature=0.8, max_tokens=2048):
            nonlocal call_count
            idx = call_count
            call_count += 1
            return responses[idx] if idx < len(responses) else None

    llm = _make_llm(FakePort())

    payload = asyncio.run(llm._resolve_payload(
        "camp-1", "actor-1", "look around", "sys", "usr",
    ))
    assert payload is not None
    assert payload["narration"] == "You look around the room."
    assert call_count == 3  # initial + 2 retries


@pytest.mark.skipif(not _HAS_TGE, reason="text_game_engine not installed")
def test_returns_none_after_retries_exhausted():
    """All retries exhausted with empty responses returns None."""
    call_count = 0

    class AlwaysEmptyPort:
        async def complete(self, system_prompt, prompt, *, temperature=0.8, max_tokens=2048):
            nonlocal call_count
            call_count += 1
            return None

    llm = _make_llm(AlwaysEmptyPort())

    payload = asyncio.run(llm._resolve_payload(
        "camp-1", "actor-1", "look around", "sys", "usr",
    ))
    assert payload is None
    assert call_count == 3  # initial + 2 retries


@pytest.mark.skipif(not _HAS_TGE, reason="text_game_engine not installed")
def test_no_retry_on_immediate_success():
    """Successful first response skips retry loop entirely."""
    retry_entered = False
    original_sleep = asyncio.sleep

    async def tracking_sleep(seconds):
        nonlocal retry_entered
        retry_entered = True
        await original_sleep(seconds)

    class ImmediatePort:
        async def complete(self, system_prompt, prompt, *, temperature=0.8, max_tokens=2048):
            return '{"narration": "Success."}'

    llm = _make_llm(ImmediatePort())

    # Monkey-patch asyncio.sleep to detect if retry loop runs
    import app.services.tge_gateway as gw_mod
    old_sleep = asyncio.sleep
    asyncio.sleep = tracking_sleep
    try:
        payload = asyncio.run(llm._resolve_payload(
            "camp-1", "actor-1", "look around", "sys", "usr",
        ))
    finally:
        asyncio.sleep = old_sleep

    assert payload is not None
    assert payload["narration"] == "Success."
    assert not retry_entered  # retry loop never ran


@pytest.mark.skipif(not _HAS_TGE, reason="text_game_engine not installed")
def test_first_retry_succeeds_skips_second():
    """Recovery on first retry means only 2 completion calls total."""
    call_count = 0
    responses = [None, '{"narration": "Recovered."}']

    class RecoverPort:
        async def complete(self, system_prompt, prompt, *, temperature=0.8, max_tokens=2048):
            nonlocal call_count
            idx = call_count
            call_count += 1
            return responses[idx] if idx < len(responses) else None

    llm = _make_llm(RecoverPort())

    payload = asyncio.run(llm._resolve_payload(
        "camp-1", "actor-1", "look around", "sys", "usr",
    ))
    assert payload is not None
    assert payload["narration"] == "Recovered."
    assert call_count == 2  # initial + 1 retry
