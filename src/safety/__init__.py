"""
Safety classification and refusal templates (P2/P4). The bypass *branch* exists in the graph;
nothing fills `safety_flags` yet.

    policy_checker.py    P2  deterministic patterns, layer 1 (also catches prompt injection)
    abuse_detection.py   P2  the model pass for veiled cases, layer 2
    refusal_templates.py P4  the approved scripts

The one thing this package must not do is collapse its signals into "bad ticket -> refuse".
Safety-critical content escalates and never refuses; a prohibited *request* refuses but still
offers the legitimate path; hostility around a legitimate request only changes the register.
"""
