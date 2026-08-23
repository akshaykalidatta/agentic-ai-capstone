"""
The model client: provider factory, on-disk response cache, rate-limit retry.

Nothing in `src/graph/` imports this yet -- it ships in P0 so the cache and retry are working
and tested before a phase depends on them.

Cache key: `sha256(provider, model, prompt, system, temperature, schema)`. Every part matters;
drop `model` and the P3 model comparison silently reuses the other model's answers.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import random
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from src.utils.config import model_config, resolve

log = logging.getLogger(__name__)


class LLMError(RuntimeError):
    """Anything that leaves us without a usable response."""


class CacheMiss(LLMError):
    """Raised only in offline mode, where a miss is a hard failure by design."""


@dataclass
class LLMResponse:
    text: str
    model: str
    cached: bool = False
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    attempts: int = 1

    def json(self) -> Any:
        """
        Parse as JSON, stripping the ``` fences models add anyway -- cheaper than a retry, and
        a retry on a formatting quirk costs a real call. Shape validation belongs to the
        caller's Pydantic model, not here.
        """
        text = self.text.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[-1]
            if text.rstrip().endswith("```"):
                text = text.rstrip()[:-3]
        return json.loads(text)


class ResponseCache:
    def __init__(self, directory: Path | str, *, enabled: bool = True, offline: bool = False):
        self.directory = Path(directory)
        self.enabled = enabled
        self.offline = offline

    @staticmethod
    def key(**parts: Any) -> str:
        # sort_keys=True, or the same dict in a different insertion order misses every time
        # while appearing to work.
        blob = json.dumps(parts, sort_keys=True, default=str, ensure_ascii=False)
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()

    def _path_for(self, key: str) -> Path:
        # Two-character shard: 900 files x dozens of runs in one flat directory is unusable.
        return self.directory / key[:2] / f"{key}.json"

    def get(self, key: str) -> dict[str, Any] | None:
        if not self.enabled:
            return None
        path = self._path_for(key)
        if not path.is_file():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            # A half-written entry from an interrupted run is a miss, not a fatal error.
            log.warning("discarding unreadable cache entry %s: %s", path.name, exc)
            return None

    def put(self, key: str, payload: dict[str, Any]) -> None:
        if not self.enabled:
            return
        path = self._path_for(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        # Atomic on POSIX and Windows, so Ctrl-C cannot leave a truncated entry behind.
        temp_path = path.with_suffix(".tmp")
        temp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(temp_path, path)


def with_retry(
    call: Callable[[], Any],
    *,
    max_attempts: int = 5,
    initial_delay: float = 2.0,
    multiplier: float = 2.0,
    max_delay: float = 60.0,
    jitter: bool = True,
    retryable: Callable[[Exception], bool] | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> tuple[Any, int]:
    """
    Exponential backoff. Returns `(result, attempts_used)`.

    Jitter matters: without it every retry in a batch waits the same 2s/4s/8s and they hammer
    the endpoint together. `sleep` is injected so the tests run the whole ladder instantly.
    """
    delay = initial_delay
    last_error: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            return call(), attempt
        except Exception as exc:
            if retryable is not None and not retryable(exc):
                raise
            last_error = exc
            if attempt == max_attempts:
                break
            wait = delay * (random.uniform(0.5, 1.0) if jitter else 1.0)
            log.warning("attempt %d/%d failed (%s); retrying in %.1fs",
                        attempt, max_attempts, exc, wait)
            sleep(wait)
            delay = min(delay * multiplier, max_delay)
    raise LLMError(f"giving up after {max_attempts} attempts: {last_error}") from last_error


def is_retryable(exc: Exception) -> bool:
    """
    Rate limits and transient server errors only. A 401 retried five times is five identical
    failures plus the false impression that the service is flaky.
    """
    retry_codes = set(
        model_config().get("retry", {}).get("retry_on_status", [429, 500, 502, 503, 504])
    )
    status = getattr(exc, "status_code", None) or getattr(
        getattr(exc, "response", None), "status_code", None
    )
    if status is not None:
        return int(status) in retry_codes
    message = str(exc).lower()
    if any(word in message for word in ("unauthorized", "invalid api key", "authentication")):
        return False
    return any(
        word in message
        for word in ("rate limit", "429", "timeout", "timed out", "502", "503", "504", "overloaded")
    )


class LLMClient:
    """
    One client per run. Constructing it touches no network and needs no API key -- the provider
    SDK is imported and the key read on the first uncached call.
    """

    def __init__(self, *, cache: ResponseCache | None = None, transport: Any | None = None):
        self.config = model_config()
        self.provider = str(self.config.get("provider", "groq"))
        cache_config = self.config.get("cache", {}) or {}
        self.cache = cache or ResponseCache(
            resolve(cache_config.get("dir", ".cache/llm")),
            enabled=bool(cache_config.get("enabled", True)),
            offline=bool(cache_config.get("offline", False)),
        )
        self._transport = transport  # injected in tests; built lazily otherwise

    def role_config(self, role: str) -> dict[str, Any]:
        roles = self.config.get("roles", {}) or {}
        if role not in roles:
            raise LLMError(f"unknown model role {role!r}; have {sorted(roles)}")
        return roles[role]

    def _transport_object(self) -> Any:
        if self._transport is None:
            if self.provider != "groq":
                raise LLMError(f"no transport implemented for provider {self.provider!r}")
            from groq import Groq

            # `.env` is already in the environment by now: `src.utils.config` loads it on
            # import, and this module imports it. Nothing here needs to know the file exists.
            api_key = os.environ.get("GROQ_API_KEY")
            if not api_key:
                raise LLMError(
                    "GROQ_API_KEY is not set. Put it in .env at the repo root "
                    "(GROQ_API_KEY=gsk_..., copy .env.example), or set it in the shell for one "
                    "run, or set cache.offline: true to work from cached responses only."
                )
            self._transport = Groq(
                api_key=api_key, timeout=float(self.config.get("timeout_seconds", 120))
            )
        return self._transport

    def complete(
        self,
        prompt: str,
        *,
        role: str = "reason",
        system: str = "",
        schema: dict[str, Any] | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        allow_fallback: bool = True,
    ) -> LLMResponse:
        """Cache, then call, then retry, then the fallback model."""
        spec = self.role_config(role)
        primary_model = str(spec["model"])
        resolved_temperature = spec.get("temperature", 0) if temperature is None else temperature
        token_limit = int(spec.get("max_tokens", 2048) if max_tokens is None else max_tokens)

        cache_key = ResponseCache.key(
            provider=self.provider,
            model=primary_model,
            prompt=prompt,
            system=system,
            temperature=resolved_temperature,
            schema=schema,
        )
        cached = self.cache.get(cache_key)
        if cached is not None:
            return LLMResponse(
                text=cached["text"],
                model=cached.get("model", primary_model),
                cached=True,
                prompt_tokens=cached.get("prompt_tokens"),
                completion_tokens=cached.get("completion_tokens"),
            )

        if self.cache.offline:
            raise CacheMiss(f"offline mode: no cached response for {primary_model}")

        retry_config = self.config.get("retry", {}) or {}
        candidate_models = [primary_model]
        if allow_fallback and spec.get("fallback"):
            candidate_models.append(str(spec["fallback"]))

        last_error: Exception | None = None
        for model_name in candidate_models:
            try:
                response, attempts = with_retry(
                    lambda m=model_name: self._raw_call(
                        m, prompt, system, resolved_temperature, token_limit, schema
                    ),
                    max_attempts=int(retry_config.get("max_attempts", 5)),
                    initial_delay=float(retry_config.get("initial_delay_seconds", 2)),
                    multiplier=float(retry_config.get("backoff_multiplier", 2.0)),
                    max_delay=float(retry_config.get("max_delay_seconds", 60)),
                    jitter=bool(retry_config.get("jitter", True)),
                    retryable=is_retryable,
                )
            except LLMError as exc:
                log.warning("model %s exhausted its retries: %s", model_name, exc)
                last_error = exc
                continue

            response.attempts = attempts
            # Cached under the PRIMARY key even when the fallback answered: the question was the
            # same, and re-asking should not depend on which model was up that day. Failed
            # calls are never cached -- a cached failure replays forever without retrying.
            self.cache.put(
                cache_key,
                {
                    "text": response.text,
                    "model": response.model,
                    "prompt_tokens": response.prompt_tokens,
                    "completion_tokens": response.completion_tokens,
                },
            )
            return response

        raise LLMError(f"all models failed for role {role!r}: {last_error}")

    def _raw_call(
        self,
        model: str,
        prompt: str,
        system: str,
        temperature: float,
        max_tokens: int,
        schema: dict[str, Any] | None,
    ) -> LLMResponse:
        """The only place that speaks the provider's wire format."""
        messages: list[dict[str, str]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        kwargs: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if schema is not None:
            kwargs["response_format"] = {"type": "json_object"}

        completion = self._transport_object().chat.completions.create(**kwargs)
        usage = getattr(completion, "usage", None)
        return LLMResponse(
            text=completion.choices[0].message.content or "",
            model=model,
            prompt_tokens=getattr(usage, "prompt_tokens", None),
            completion_tokens=getattr(usage, "completion_tokens", None),
        )


_default_client: LLMClient | None = None


def default_client() -> LLMClient:
    global _default_client
    if _default_client is None:
        _default_client = LLMClient()
    return _default_client


def set_default_client(client: LLMClient | None) -> None:
    """Injection point for tests. Pass None to reset to a real client."""
    global _default_client
    _default_client = client
