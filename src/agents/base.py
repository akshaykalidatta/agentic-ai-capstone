"""
Structured model calls: prompt in, validated Pydantic model out.

Every agent in this package goes through `call_structured`. It exists because the failure mode
that matters here is not "the model was wrong" -- it is "the model returned something that did
not parse, and the node crashed 90 tickets into a 150-ticket run".

Three layers of defence, in order of cost:

1. **Ask for JSON.** `response_format={"type": "json_object"}`, plus the schema in the prompt.
2. **Repair once.** On a parse or validation error, send the model its own output and the
   error, and ask for a correction. Most failures are a trailing comma or a missing field.
3. **Degrade, do not crash.** If repair fails, raise `StructuredOutputError`; the caller
   decides what a safe default looks like. For every agent here that default routes to a
   human, never to AUTO_RESOLVE.

The repair pass is capped at one. A model that cannot produce valid JSON twice will not manage
it on the third try, and each attempt is a real call against a rate-limited free tier.
"""

from __future__ import annotations

import json
import logging
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

from src.utils.llm import LLMClient, default_client

log = logging.getLogger(__name__)

ModelT = TypeVar("ModelT", bound=BaseModel)


class StructuredOutputError(RuntimeError):
    """The model could not produce output matching the schema, even after a repair pass."""


def schema_hint(model_cls: type[BaseModel]) -> str:
    """
    A compact JSON-schema description for the prompt.

    Pydantic's full `model_json_schema()` is verbose enough to crowd out the actual policy
    text in the context window, so this trims it to the properties and the required list --
    which is all the model needs to produce the right shape.
    """
    schema = model_cls.model_json_schema()
    properties = {}
    for name, spec in (schema.get("properties") or {}).items():
        entry = {"type": spec.get("type", spec.get("anyOf", "any"))}
        if spec.get("description"):
            entry["description"] = spec["description"]
        if spec.get("enum"):
            entry["enum"] = spec["enum"]
        properties[name] = entry
    return json.dumps(
        {"properties": properties, "required": schema.get("required", [])},
        ensure_ascii=False,
        indent=1,
    )


def call_structured(
    prompt: str,
    model_cls: type[ModelT],
    *,
    role: str = "reason",
    system: str = "",
    client: LLMClient | None = None,
    allow_repair: bool = True,
) -> ModelT:
    """Call the model and return a validated `model_cls`, or raise `StructuredOutputError`."""
    client = client or default_client()
    full_prompt = f"{prompt}\n\nReturn ONLY a JSON object with this shape:\n{schema_hint(model_cls)}"

    try:
        response = client.complete(
            full_prompt, role=role, system=system, schema=model_cls.model_json_schema()
        )
    except Exception as exc:
        # Deliberately broad. `LLMError` covers the failures we anticipated -- rate limits,
        # exhausted retries, a missing key. A provider SDK can also raise its own connection,
        # SSL or protocol errors, and those crashed the triage node the first time an outage
        # was simulated. Every model failure has to arrive at the caller as the same type, so
        # that "the model is unavailable" has exactly one handler instead of one per SDK
        # exception nobody predicted.
        raise StructuredOutputError(f"{model_cls.__name__}: call failed: {exc}") from exc

    try:
        return model_cls.model_validate(response.json())
    except (json.JSONDecodeError, ValidationError, TypeError) as exc:
        # Bind it to an outer name: Python unbinds `exc` when the except block exits, so
        # referencing it in the repair prompt below would raise NameError instead.
        first_error = exc
        if not allow_repair:
            raise StructuredOutputError(f"{model_cls.__name__}: {exc}") from exc
        log.warning("%s did not validate (%s); attempting one repair", model_cls.__name__, exc)

    repair_prompt = (
        f"{full_prompt}\n\nYour previous answer was rejected.\n"
        f"--- your answer ---\n{response.text}\n"
        f"--- the error ---\n{first_error}\n\n"
        "Return the corrected JSON object only. No commentary, no code fences."
    )
    try:
        repaired = client.complete(
            repair_prompt, role=role, system=system, schema=model_cls.model_json_schema()
        )
        return model_cls.model_validate(repaired.json())
    except Exception as repair_error:
        raise StructuredOutputError(
            f"{model_cls.__name__} failed twice: {repair_error}"
        ) from repair_error


def format_context(chunks: list[Any], *, max_chars: int = 12000) -> str:
    """
    Render retrieved chunks for a prompt, truncating from the end.

    Truncation is by character budget rather than chunk count because clause lengths vary by
    5x, and a fixed count either wastes the window or overflows it. Chunks arrive in relevance
    order, so dropping from the end drops the least relevant.
    """
    blocks: list[str] = []
    used = 0
    for chunk in chunks:
        label = chunk.policy_id or chunk.title or chunk.chunk_id
        tag = "" if chunk.citable else "  [INTERNAL - do not quote or cite to the customer]"
        block = f"[{label}]{tag}\nsource: {chunk.source_file}\n{chunk.text}"
        if used + len(block) > max_chars:
            log.debug("context truncated at %d chunks (%d chars)", len(blocks), used)
            break
        blocks.append(block)
        used += len(block)
    return "\n\n---\n\n".join(blocks)
