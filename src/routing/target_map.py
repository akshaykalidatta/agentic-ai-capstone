"""
Which internal queue a case goes to.

Route and target are **orthogonal** (HLD §5.2). 52 tickets are ESCALATE but 59 carry a target:
the other seven are REFUSE cases that still open a file internally -- structuring reports,
conduct cases. Treating the target as a property of the ESCALATE route alone makes those seven
unrepresentable.

Every string here must match `expected_escalation_target` in the golden set exactly. A right
decision sent to a differently-spelled queue scores as a wrong one, so this is a contract with
`data/evaluation/`, not a naming preference.
"""

from __future__ import annotations

from src.utils.config import routing_rules
from src.utils.schemas import SafetyFlag

# Product area -> the operations queue that owns it. Used when nothing more specific fires;
# several of these appear once in the whole dataset, which is why HLD §12 flags exact-target
# accuracy as worth reporting next to a coarser department-family metric.
PRODUCT_AREA_TARGETS: dict[str, str] = {
    "wire": "Wire Operations",
    "zelle": "Payments Operations",
    "transfers": "Payments Operations",
    "bill_pay": "Payments Operations",
    "mobile_deposit": "Deposit Operations",
    "online_banking": "Digital Servicing",
    "mobile_app": "Digital Support Engineering",
    "statements": "Deposit Operations",
    "safe_deposit": "Branch Operations",
    "mortgage": "Mortgage Servicing",
    "ira": "Retirement Services",
    "cd": "Deposit Operations",
    "treasury": "Treasury Management Support",
    "business_checking": "Treasury Management Support",
    "estate": "Estate & Trust Servicing",
}

CATEGORY_TARGETS: dict[str, str] = {
    "disputes_and_fees": "Claims Specialist",
    "payments_troubleshooting": "Payments Operations",
    "digital_access": "Digital Servicing",
    "account_servicing_and_closure": "Account Review",
    "conduct_and_prohibited": "Conduct Review",
}


def resolve_target(
    *,
    route: str,
    safety_flags: list[SafetyFlag],
    rule_reason: str = "",
    category: str = "",
    product_area: str = "",
    no_policy_found: bool = False,
) -> tuple[str | None, bool]:
    """
    Returns `(target, visible_to_customer)`.

    Resolution order is most-specific-first, because a safety code says more about where a
    case belongs than its product area does.
    """
    rules = routing_rules()
    safety_targets = rules.get("safety_escalation_targets", {}) or {}
    silent_codes = set(rules.get("silent_escalation_codes", []) or [])
    clause_targets = rules.get("escalation_targets", {}) or {}

    codes = [flag.code for flag in safety_flags]
    visible = not any(code in silent_codes for code in codes)

    # 1. A safety code names its own queue.
    for code in codes:
        target = safety_targets.get(code)
        if target:
            return target, visible

    # 2. A clause the rule engine cited (FEE-006 -> Service Recovery, DSP-003 -> Claims).
    for clause_id, target in clause_targets.items():
        if target and clause_id in rule_reason:
            return target, visible

    if route not in {"ESCALATE", "REFUSE"}:
        return None, visible

    # 3. No policy covers it: a human has to decide whether one should.
    if no_policy_found:
        return PRODUCT_AREA_TARGETS.get(product_area, "Account Review"), visible

    # 4. Product area, then category. A REFUSE with nothing else to go on opens no file.
    target = PRODUCT_AREA_TARGETS.get(product_area) or CATEGORY_TARGETS.get(category)
    if route == "REFUSE" and not any(code in safety_targets for code in codes):
        return None, visible
    return target, visible
