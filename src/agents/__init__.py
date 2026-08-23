"""
Prompt construction and structured parsing, one module per job. Empty in P0 -- the nodes are
deterministic stubs, and a prompt written before there is a measurement to move is a guess.

    triage.py    P2   sentiment, intent, entities, the model half of safety classification
    policy.py    P3   the `analyse_policy` structured call
    rag.py       P3   the LLM query rewrite that `refine_query` falls back from
    response.py  P4   route-specific drafting

Every module here calls `src.utils.llm.default_client()` and returns a Pydantic model. No agent
touches state, and no node builds a prompt.
"""
