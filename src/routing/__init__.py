"""
The deterministic rule engine (P3) and the escalation-target map.

    rules_engine.py  preconditions computed from customer_context; proposes `rule_route`
    target_map.py    (route, safety code, category) -> internal queue

The engine reads fields, never prose -- that boundary is what makes the rules auditable by a
compliance reviewer who does not read Python. It need not be complete, only correct where it
fires: `rule_route = None` is a legitimate answer meaning "no rule covers this ticket".

P0 has two worked preconditions inlined in `nodes.preconditions`; they move here in P3.
"""
