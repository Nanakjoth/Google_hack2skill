"""
Agent 2 - Resource Allocator.

Filters the live hospital list down to facilities that can *physically* treat
this case: a free ICU bed, the platelet units, the named specialist, and every
drug in the order.

This agent is deliberately NOT backed by the model. Whether a hospital has a
bed is a fact about inventory, and a model must never be the thing asserting
it. Agent 1 proposes what the patient needs; this agent decides whether the
network can supply it, using arithmetic.

It also returns why each facility was rejected - a command centre that only
shows "no match" is useless to the person who has to fix it.

CONNECT LATER: replace `hospitals` with a live query against your real
hospital inventory system. The filtering logic itself won't need to change.
"""

from data_store import (
    hospitals, stock_of, medicines_catalog,
    resolve_specialty, doctors_of,
)


def _evaluate(h: dict, need: dict) -> list:
    """Reasons this facility cannot take the case. Empty == eligible."""
    problems = []
    if h["icu"] < need["icu"]:
        problems.append(f"needs {need['icu']} ICU bed(s), has {h['icu']} free")

    # Specialty check moved from a facility boolean to an actual doctor roster.
    # The boolean said "this hospital has a cardiologist somewhere"; the roster
    # answers the question routing actually needs - is there a doctor here who
    # can take this case *right now*. A facility with a cardiologist on paper
    # but nobody with free capacity is not eligible, and that distinction is
    # exactly what the doctor's queue needs to see.
    specialty = resolve_specialty(need.get("specialist"))
    if specialty:
        roster = doctors_of(h, specialty)
        if not roster:
            problems.append(f"no {specialty.replace('_', ' ')} on staff")
        elif not any(d["load"] < d["capacity"] for d in roster):
            problems.append(
                f"all {specialty.replace('_', ' ')} doctor(s) at capacity"
            )

    if stock_of(h, "platelet_concentrate") < need["platelets"]:
        have = stock_of(h, "platelet_concentrate")
        problems.append(f"needs {need['platelets']} platelet unit(s), has {have}")
    for med, qty in need.get("medicines", {}).items():
        if med == "platelet_concentrate":
            continue  # already counted above; one physical stock, one check
        if med not in medicines_catalog:
            problems.append(f"unknown medicine '{med}' (not in catalog)")
        elif stock_of(h, med) < qty:
            problems.append(f"{med}: needs {qty}, has {stock_of(h, med)}")
    return problems


def run(need: dict):
    eligible, rejected = [], []
    for h in hospitals:
        problems = _evaluate(h, need)
        if problems:
            rejected.append({"id": h["id"], "name": h["name"], "reasons": problems})
        else:
            eligible.append(h)

    if eligible:
        text = (
            f"{len(eligible)} of {len(hospitals)} facilities have the physical capacity: "
            + ", ".join(h["name"] for h in eligible) + "."
        )
    else:
        text = (
            "No facility in the network currently holds the required "
            "beds/stock/specialist. Reasons by facility: "
            + "; ".join(f"{r['name']} - {', '.join(r['reasons'])}" for r in rejected)
        )

    step = {
        "title": "Agent 2 - Resource Allocator",
        "text": text,
        "source": "deterministic",
        "eligible": [h["id"] for h in eligible],
        "rejected": rejected,
    }
    return eligible, step
