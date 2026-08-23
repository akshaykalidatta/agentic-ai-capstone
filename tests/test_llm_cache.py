"""
The LLM client's cache and retry, tested with a fake transport and an injected `sleep`, so the
whole file runs in milliseconds and needs no network or API key.

    python -m pytest tests/test_llm_cache.py -v
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from src.utils.llm import CacheMiss, LLMClient, LLMError, ResponseCache, is_retryable, with_retry


@dataclass
class FakeTransport:
    """Duck-types just enough of the Groq client: `.chat.completions.create(**kwargs)`."""

    replies: list[Any] = field(default_factory=list)
    calls: list[dict] = field(default_factory=list)

    def __post_init__(self):
        transport = self

        class Completions:
            def create(self, **kwargs):
                transport.calls.append(kwargs)
                reply = transport.replies.pop(0) if transport.replies else "ok"
                if isinstance(reply, Exception):
                    raise reply
                return _fake_completion(reply)

        class Chat:
            completions = Completions()

        self.chat = Chat()


def _fake_completion(text: str):
    class Message:
        content = text

    class Choice:
        message = Message()

    class Usage:
        prompt_tokens = 11
        completion_tokens = 7

    class Completion:
        choices = [Choice()]
        usage = Usage()

    return Completion()


class RateLimited(Exception):
    status_code = 429


class BadApiKey(Exception):
    status_code = 401


@pytest.fixture
def client(tmp_path):
    return LLMClient(cache=ResponseCache(tmp_path / "llm"), transport=FakeTransport())


# ------------------------------------------------------------------------------- the cache


def test_first_call_hits_the_transport_and_second_hits_the_cache(client):
    first = client.complete("what is FEE-001?", role="fast")
    second = client.complete("what is FEE-001?", role="fast")

    assert first.cached is False
    assert second.cached is True
    assert second.text == first.text
    assert len(client._transport.calls) == 1  # one network call, two answers


def test_the_key_separates_models(client):
    """
    P3 compares two models on the same prompts. Without `model` in the key the second reads the
    first's answers and the comparison returns "identical accuracy" -- believable, meaningless.
    """
    client.complete("same prompt", role="fast")
    client.complete("same prompt", role="reason")
    assert len(client._transport.calls) == 2


def test_the_key_separates_system_prompt_temperature_and_schema():
    base = dict(provider="groq", model="m", prompt="p", system="", temperature=0, schema=None)
    key = ResponseCache.key(**base)
    assert ResponseCache.key(**{**base, "system": "you are terse"}) != key
    assert ResponseCache.key(**{**base, "temperature": 0.7}) != key
    assert ResponseCache.key(**{**base, "schema": {"type": "object"}}) != key


def test_the_key_is_insensitive_to_dict_ordering():
    """Without `sort_keys=True` the cache misses every call while appearing to work."""
    assert ResponseCache.key(model="m", prompt="p") == ResponseCache.key(prompt="p", model="m")


def test_a_corrupt_cache_entry_is_treated_as_a_miss(client, tmp_path):
    """An interrupted run must not poison the next one."""
    client.complete("hello", role="fast")
    next((tmp_path / "llm").rglob("*.json")).write_text("{ this is not json")

    assert client.complete("hello", role="fast").cached is False
    assert len(client._transport.calls) == 2


def test_offline_mode_raises_on_a_miss(tmp_path):
    """Used to prove an eval run touched no network, and to re-score a finished run."""
    client = LLMClient(
        cache=ResponseCache(tmp_path / "llm", offline=True), transport=FakeTransport()
    )
    with pytest.raises(CacheMiss):
        client.complete("never asked before", role="fast")
    assert client._transport.calls == []


def test_offline_mode_serves_a_hit(tmp_path):
    warm = LLMClient(cache=ResponseCache(tmp_path / "llm"), transport=FakeTransport())
    warm.complete("known question", role="fast")

    offline = LLMClient(
        cache=ResponseCache(tmp_path / "llm", offline=True), transport=FakeTransport()
    )
    assert offline.complete("known question", role="fast").cached is True


def test_json_helper_strips_the_fences_models_add_anyway(client):
    client._transport.replies = ['```json\n{"route": "ESCALATE"}\n```']
    assert client.complete("give me json", role="fast").json() == {"route": "ESCALATE"}


# ----------------------------------------------------------------------------------- retry


def test_retries_a_rate_limit_then_succeeds():
    attempts_made = {"count": 0}

    def flaky():
        attempts_made["count"] += 1
        if attempts_made["count"] < 3:
            raise RateLimited("rate limit reached")
        return "done"

    result, attempts = with_retry(
        flaky, initial_delay=0, retryable=is_retryable, sleep=lambda _: None
    )
    assert (result, attempts) == ("done", 3)


def test_does_not_retry_a_bad_api_key():
    """A 401 retried five times is five identical failures and a misleading "flaky service"."""
    attempts_made = {"count": 0}

    def unauthorized():
        attempts_made["count"] += 1
        raise BadApiKey("unauthorized")

    with pytest.raises(BadApiKey):
        with_retry(unauthorized, initial_delay=0, retryable=is_retryable, sleep=lambda _: None)
    assert attempts_made["count"] == 1


def test_gives_up_loudly_after_max_attempts():
    def always_rate_limited():
        raise RateLimited("429")

    with pytest.raises(LLMError):
        with_retry(
            always_rate_limited,
            max_attempts=3,
            initial_delay=0,
            retryable=is_retryable,
            sleep=lambda _: None,
        )


def test_backoff_grows_and_is_capped():
    waits: list[float] = []

    def always_rate_limited():
        raise RateLimited("429")

    with pytest.raises(LLMError):
        with_retry(
            always_rate_limited,
            max_attempts=5,
            initial_delay=1,
            multiplier=2,
            max_delay=4,
            jitter=False,
            retryable=is_retryable,
            sleep=waits.append,
        )
    assert waits == [1, 2, 4, 4]  # doubling, then clamped


def test_failed_calls_are_not_cached(client, tmp_path):
    """A cached failure replays forever without ever retrying -- worse than no cache."""
    client._transport.replies = [RateLimited("429")] * 10
    with pytest.raises(LLMError):
        client.complete("doomed", role="fast")
    assert list((tmp_path / "llm").rglob("*.json")) == []
