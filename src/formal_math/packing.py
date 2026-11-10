"""Whole-record evidence packing. Model-specific token checks happen in providers."""
from __future__ import annotations

import json


def declarations(hits: list[dict], max_chars: int) -> list[dict]:
    selected, seen = [], set()
    for hit in hits:
        name = hit.get("exact_name") or hit.get("name")
        if not name or name in seen:
            continue
        item = {"exact_name": str(name), "lean_source": hit.get("lean_source", hit.get("source_text")),
                "description": hit.get("description"), "data_version": hit.get("data_version")}
        for variant in (item, {k: v for k, v in item.items() if k != "description"}):
            if len(json.dumps([*selected, variant], ensure_ascii=False)) <= max_chars:
                selected.append(variant)
                seen.add(name)
                break
    return selected


def feedback(result: dict, max_chars: int) -> dict:
    """Deduplicate complete diagnostic lines within one shared feedback allowance."""
    goal = str(result.get("goal") or "")
    # A proof state is advisory. Do not silently present a cut state as complete.
    selected_goal = goal if len(goal) <= max_chars else ""
    remaining = max_chars - len(selected_goal)
    diagnostics = result.get("diagnostics") or ""
    if isinstance(diagnostics, (tuple, list)):
        diagnostics = "\n".join(map(str, diagnostics))
    lines, seen = [], set()
    for line in str(diagnostics).splitlines():
        if line in seen or not line.strip():
            continue
        seen.add(line)
        if len(line) + sum(len(v) + 1 for v in lines) <= remaining:
            lines.append(line)
    return {"goal": selected_goal, "diagnostics": "\n".join(lines),
            "goal_omitted": bool(goal and not selected_goal),
            "diagnostics_excerpted": "\n".join(lines) != str(diagnostics)}


def failures(records: list[dict], max_chars: int = 6000, max_pairs: int = 2) -> list[dict]:
    selected = []
    for record in reversed(records[-max_pairs:]):
        candidate = str(record.get("candidate", ""))
        diagnostic = str(record.get("diagnostics", ""))
        item = {"attempt": record.get("attempt"), "status": "rejected",
                "candidate": candidate[:1200], "diagnostics": diagnostic[:800],
                "excerpted": len(candidate) > 1200 or len(diagnostic) > 800}
        if len(json.dumps([item, *selected], ensure_ascii=False)) <= max_chars:
            selected.insert(0, item)
    return selected


def packet(task: str, result: dict, hits: list[dict], records: list[dict],
           config: dict, role: str, **advice) -> dict:
    r, limits = config["retrieval"], config["limits"]
    cap = r["informal_chars"] if role.startswith("informal_") else (
        r["discussion_chars"] if role == "discussion" else r["fresh_chars"]
        if role == "fresh_formal" else r["formal_chars"])
    current = feedback(result, limits["feedback_chars"])
    output = {"task": task, "goal": current["goal"],
              "diagnostics": current["diagnostics"],
              "feedback_truncated": current["goal_omitted"] or current["diagnostics_excerpted"],
              "retrieved_declarations": declarations(hits, cap),
              "failure_history": failures(records, limits["failure_chars"], limits["failure_pairs"])}
    output.update(advice)
    if role.startswith("informal_"):
        # The reviewer receives the same task evidence, not the generator transcript.
        while len(json.dumps(output, ensure_ascii=False)) > limits["informal_packet_chars"]:
            if output["retrieved_declarations"]:
                output["retrieved_declarations"].pop()
            elif output["failure_history"]:
                output["failure_history"].pop(0)
            else:
                break  # Provider checks immutable task/goal against the exact token cap.
    return output
