"""
A scripted model, so the real agent code paths are testable with no API key and no network.

`ScriptedTransport` duck-types the Groq client and answers by looking at which prompt it was
handed -- triage, policy analysis, route proposal or drafting. That means the *agents* under
test are the real ones: real prompt construction, real JSON parsing, real validation, real
citation filtering. Only the model is fake.

This is the difference between "the graph is wired correctly" (which the topology tests already
prove) and "the pipeline produces a decision" (which needs something to reason).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from src.utils.llm import LLMClient, ResponseCache


def _completion(text: str):
    class Message:
        content = text

    class Choice:
        message = Message()

    class Usage:
        prompt_tokens = 100
        completion_tokens = 40

    class Completion:
        choices = [Choice()]
        usage = Usage()

    return Completion()


# Recognises which agent is calling from a phrase unique to its prompt.
TRIAGE_MARKER = "Classify this support ticket"
ANALYSIS_MARKER = "Which clauses decide this?"
ROUTING_MARKER = "Choose the route."
DRAFTING_MARKER = "Write the reply."


@dataclass
class ScriptedTransport:
    """
    Answers each agent with a canned, valid response. Override any of the four to script a
    specific behaviour; set `raise_on` to simulate an outage.
    """

    triage: dict[str, Any] | None = None
    analysis: dict[str, Any] | None = None
    routing: dict[str, Any] | None = None
    drafting: dict[str, Any] | None = None
    malformed: set[str] = field(default_factory=set)  # agents that should return bad JSON once
    raise_on: set[str] = field(default_factory=set)  # agents that should fail entirely
    calls: list[dict[str, Any]] = field(default_factory=list)
    _seen_malformed: set[str] = field(default_factory=set)

    def __post_init__(self):
        transport = self

        class Completions:
            def create(self, **kwargs):
                return transport._respond(**kwargs)

        class Chat:
            completions = Completions()

        self.chat = Chat()

    def _kind(self, prompt: str) -> str:
        for marker, kind in (
            (TRIAGE_MARKER, "triage"),
            (ANALYSIS_MARKER, "analysis"),
            (ROUTING_MARKER, "routing"),
            (DRAFTING_MARKER, "drafting"),
        ):
            if marker in prompt:
                return kind
        return "unknown"

    def _respond(self, **kwargs):
        prompt = kwargs["messages"][-1]["content"]
        kind = self._kind(prompt)
        self.calls.append({"kind": kind, "model": kwargs.get("model"), "prompt": prompt})

        if kind in self.raise_on:
            raise RuntimeError(f"simulated outage for {kind}")

        # Malformed once, then correct: exercises the repair pass in `agents.base`.
        if kind in self.malformed and kind not in self._seen_malformed:
            self._seen_malformed.add(kind)
            return _completion("{ this is not json")

        payload = {
            "triage": self.triage or DEFAULT_TRIAGE,
            "analysis": self.analysis or DEFAULT_ANALYSIS,
            "routing": self.routing or DEFAULT_ROUTING,
            "drafting": self.drafting or DEFAULT_DRAFTING,
        }.get(kind, {})
        return _completion(json.dumps(payload))


DEFAULT_TRIAGE: dict[str, Any] = {
    "sentiment": "neutral",
    "intent": "overdraft fee reversal request",
    "entities": {"amount": 35.0, "fee_date": "2026-08-04", "fee_reversal_requested": True},
    "hostile_tone": False,
    "additional_safety_codes": [],
    "safety_reasoning": "",
}

DEFAULT_ANALYSIS: dict[str, Any] = {
    "deciding_clauses": [{"policy_id": "FEE-001", "why": "one-time courtesy reversal applies"}],
    "constraining_clauses": [],
    "missing_facts": [],
    "policy_verified": True,
    "conflicts": [],
    "self_certainty": 0.8,
}

DEFAULT_ROUTING: dict[str, Any] = {
    "route": "AUTO_RESOLVE",
    "rationale": "FEE-001 conditions met",
    "escalation_target": None,
}

DEFAULT_DRAFTING: dict[str, Any] = {
    "body": "We have reversed the $35 overdraft fee as a one-time courtesy under FEE-001.",
    "cited_policy_ids": ["FEE-001"],
}


def scripted_client(tmp_path, **kwargs) -> LLMClient:
    """An LLMClient wired to a ScriptedTransport, with a throwaway cache directory."""
    transport = ScriptedTransport(**kwargs)
    return LLMClient(cache=ResponseCache(tmp_path / "llm-cache"), transport=transport)
