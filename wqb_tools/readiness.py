"""(3) submission readiness, (7) Power Pool description drafting/checking, (8) active rules & themes."""
from __future__ import annotations

import difflib
import re
from typing import Any, Dict, Iterable, List, Optional, Sequence

from .client import BrainClient, get_client


# ------------------------------------------------------------------ (8) rules & themes
def active_rules(sample_alpha_id: str, client: BrainClient | None = None) -> Dict[str, Any]:
    """What the platform currently enforces for this alpha's scope, read from its official check:
    matched / unmatched themes (name, multiplier), submission quotas, and every test's limit.
    Use an UNSUBMITTED FULL-mode alpha from the scope you care about."""
    from .alphas import check_submission

    chk = check_submission(sample_alpha_id, client=client)
    out: Dict[str, Any] = {"themes_matched": [], "themes_not_matched": [], "quotas": {}, "limits": {}}
    for c in chk.get("checks") or []:
        n = c["name"]
        if n == "MATCHES_THEMES":
            key = "themes_matched" if c.get("result") == "PASS" else "themes_not_matched"
            out[key] += [{"id": t.get("id"), "name": t.get("name"), "multiplier": t.get("multiplier")}
                         for t in c.get("themes") or []]
        elif n.endswith("_SUBMISSION"):
            out["quotas"][n] = {"used": c.get("value"), "limit": c.get("limit"), "result": c.get("result")}
        elif "limit" in c:
            out["limits"][n] = c.get("limit")
    out["power_pool_themes_active"] = [t["name"] for t in out["themes_matched"] + out["themes_not_matched"]
                                       if "Power Pool" in (t["name"] or "")]
    return out


# ------------------------------------------------------------------ (7) descriptions
_SECTIONS = ("idea", "rationale for data", "rationale for operators")


def check_description(text: str, expression: str | None = None, others: Iterable[str] = ()) -> Dict[str, Any]:
    """Power Pool description rules (docs + help article): >= 100 characters; Idea / Rationale for data used /
    Rationale for operators used; must NOT contain the alpha expression; should be unique across your alphas."""
    errors, warnings = [], []
    t = text or ""
    if len(t) < 100:
        errors.append(f"too short: {len(t)} < 100 characters")
    low = t.lower()
    for s in _SECTIONS:
        if s not in low:
            errors.append(f"missing section '{s.title()}'")
    if expression:
        compact = re.sub(r"\s+", "", expression)
        if compact and compact in re.sub(r"\s+", "", t):
            errors.append("contains the alpha expression (not allowed)")
        calls = re.findall(r"[A-Za-z_]\w*\([^()]*\)", t)
        if len(calls) >= 2:
            warnings.append(f"looks like it quotes code fragments: {calls[:3]}")
    for o in others:
        ratio = difflib.SequenceMatcher(None, t, o or "").ratio()
        if ratio > 0.85:
            errors.append(f"near-duplicate of an existing description (similarity {ratio:.2f})")
            break
    return {"ok": not errors, "errors": errors, "warnings": warnings, "length": len(t)}


def draft_pp_description(alpha_id: str, idea: str, operator_notes: Dict[str, str] | None = None,
                         client: BrainClient | None = None) -> Dict[str, Any]:
    """Draft the three-part description. `idea` (the economic hypothesis) must come from the researcher; the data and
    operator rationales are drafted from field and operator descriptions. Returns {'text', 'check'}."""
    c = client or get_client()
    from .alphas import get_alpha
    from .meta import list_operators
    from .validate import field_info, parse_expression

    a = get_alpha(alpha_id, c)
    expr = (a.get("regular") or {}).get("code") or ""
    st = a.get("settings") or {}
    stmts, _ = parse_expression(expr)
    names, idents = set(), []

    def walk(n):
        if n["t"] == "call":
            names.add(n.get("infix") and n["name"] or n["name"])
            for x in n["args"] + list(n["kwargs"].values()):
                walk(x)
        elif n["t"] == "id":
            idents.append(n["name"])

    for s in stmts:
        walk(s["value"])
    from .validate import GROUP_KEYWORDS

    groups = sorted({i for i in idents if i in GROUP_KEYWORDS})
    finfo = field_info({i for i in idents if i not in GROUP_KEYWORDS}, st.get("region", "USA"), st.get("delay", 1),
                       st.get("universe", "TOP3000"), c)
    fields = {f: v for f, v in finfo.items() if v and str(v.get("type")).upper() != "GROUP"}
    datasets = sorted({v["dataset"] for v in fields.values() if v.get("dataset")})
    data_part = "; ".join(f"{f} is {(v.get('description') or 'a data field').rstrip('.')}" for f, v in fields.items())
    if groups:
        data_part += f"; {', '.join(groups)} is used only as a grouping (peer set), not as a data input"
    op_desc = {o["name"]: o.get("description") or "" for o in list_operators(c)}
    notes = dict(operator_notes or {})
    op_lines = []
    for n in sorted(names):
        if n in ("add", "subtract", "multiply", "divide", "reverse"):
            continue
        first_sentence = re.split(r"(?<=\.)\s", op_desc.get(n, "").strip())[0].rstrip(".")
        op_lines.append(f"{n}: {notes.get(n) or first_sentence}")
    if {"add", "multiply"} & names:
        op_lines.append(notes.get("combine", "the weighted sum blends the components into one signal"))
    neut = st.get("neutralization")
    if neut:
        op_lines.append(f"{neut} neutralization in settings removes common exposure so the signal is stock-specific")
    text = (f"Idea: {idea.strip()}\n"
            f"Rationale for data used: Fields from {', '.join(datasets) or 'one dataset'}: {data_part}.\n"
            f"Rationale for operators used: " + "; ".join(op_lines) + ".")
    return {"text": text, "check": check_description(text, expr)}


# ------------------------------------------------------------------ (3) readiness
def submission_readiness(candidates: Sequence[str], purpose: str = "power_pool", quota_left: int | None = None,
                         min_quality: float = 45.0, client: BrainClient | None = None) -> Dict[str, Any]:
    """One call before submitting: classify each candidate (official check), robustness report, local correlation
    plan against the right submitted pool and against each other, then recommend what to submit and in which order.
    purpose='power_pool' (pure PP: PP pool, threshold 0.5) or 'regular' (SELF pool, threshold 0.7)."""
    c = client or get_client()
    from .corr import plan_submission_order
    from .pp import classify_alpha

    from .quality import robustness_report

    report = []
    for a in dict.fromkeys(candidates):
        cl = classify_alpha(a, c)
        rb = robustness_report(a, c)
        report.append({"alpha_id": a, "label": cl["label"], "submittable": cl["submittable"],
                       "sharpe": cl["sharpe"], "quality": rb["quality_score"], "flags": rb["flags"],
                       "pp_blockers": cl["pp_blockers"], "regular_blockers": cl["regular_blockers"],
                       "description_missing": cl["description_missing"], "pp_themes": cl["pp_themes_matched"]})
    want = (lambda r: r["label"] != "NONE") if purpose == "power_pool" else (lambda r: "REGULAR" in r["label"])
    eligible = [r for r in report if want(r) and r["quality"] >= min_quality]
    plan = plan_submission_order([r["alpha_id"] for r in eligible],
                                 kind="power_pool" if purpose == "power_pool" else "regular",
                                 score={r["alpha_id"]: r["quality"] for r in eligible}, client=c) if eligible else \
        {"order": [], "dropped": []}
    order = plan["order"][:quota_left] if quota_left is not None else plan["order"]
    todo = []
    for a in order:
        r = next(x for x in report if x["alpha_id"] == a)
        if r["description_missing"]:
            todo.append(f"{a}: set a Power Pool description first")
    return {"recommended_order": order, "not_recommended": [r for r in report if r["alpha_id"] not in order],
            "correlation_dropped": plan.get("dropped", []), "todo": todo, "details": report,
            "note": "correlation tests only see SUBMITTED alphas - re-run after every submission"}
