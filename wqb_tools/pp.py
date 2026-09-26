"""Power Pool helpers: operator/field budget and candidate classification (Pure PP / PP+ATOM / PP+Regular ...).

Rules (BRAIN docs "Power Pool Alphas", checked 2026-09):
  Sharpe >= 1.0; operators (incl. repeats) <= 8, ts_backfill / group_backfill not counted;
  unique data fields (excluding grouping fields) <= 3; Power Pool correlation < 0.5; turnover, sub-universe and
  robust-universe tests PASS; must match an active Power Pool theme; description >= 100 chars (Idea / Rationale).
Operator counting matches the platform's `regular.operatorCount`: every function call and every infix operator,
including unary minus, is one operator.
"""
from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional

from .client import BrainClient, get_client
from .expr import analyze_expression, tokenize

PP_MAX_OPERATORS = 8
PP_MAX_FIELDS = 3
PP_MIN_SHARPE = 1.0
PP_MAX_PP_CORRELATION = 0.5
FREE_OPERATORS = {"ts_backfill", "group_backfill"}
GROUPING_FIELDS = {"country", "industry", "subindustry", "currency", "market", "sector", "exchange"}
_INFIX = {"+", "-", "*", "/", "^", "<", ">", "<=", ">=", "==", "!=", "&&", "||", "?", "%"}
# performance tests that must be PASS (not FAIL, not WARNING) for a Regular alpha
_PERF_PREFIXES = ("LOW_", "HIGH_", "CONCENTRATED_", "SELF_CORRELATION", "PROD_CORRELATION", "ROBUST")


# ------------------------------------------------------------------ operator / field budget
def operator_count(expression: str) -> Dict[str, int]:
    """Count operators the way the platform does (functions + infix operators incl. unary minus).
    Returns {'total', 'free' (ts_backfill/group_backfill calls), 'pp' (= total - free)}."""
    toks = tokenize(expression)
    total = free = 0
    for i, (kind, val, _) in enumerate(toks):
        nxt = toks[i + 1] if i + 1 < len(toks) else None
        prev = toks[i - 1] if i else None
        if kind == "id" and nxt is not None and nxt[1] == "(":
            total += 1
            if val in FREE_OPERATORS:
                free += 1
        elif kind == "op" and val in _INFIX:
            if val == "+" and (prev is None or (prev[0] == "op" and prev[1] != ")")):
                continue  # unary plus is a no-op
            total += 1  # binary operators and unary minus ("reverse") both count
    return {"total": total, "free": free, "pp": total - free}


def field_datasets(
    fields: Iterable[str],
    region: str = "USA",
    delay: int = 1,
    universe: str = "TOP3000",
    client: BrainClient | None = None,
) -> Dict[str, Optional[str]]:
    """Map data-field ids to their dataset id (via validate.field_info, shared disk cache). Unknown ids -> None."""
    from .validate import field_info

    info = field_info(fields, region, delay, universe, client)
    return {f: (v or {}).get("dataset") for f, v in info.items()}


def pp_budget(
    expression: str | None = None,
    *,
    alpha_id: str | None = None,
    alpha: Dict[str, Any] | None = None,
    region: str | None = None,
    delay: int | None = None,
    universe: str | None = None,
    resolve_datasets: bool = True,
    client: BrainClient | None = None,
) -> Dict[str, Any]:
    """Power Pool budget of an expression (or of a simulated alpha).
    For a simulated alpha the platform's regular.operatorCount is used as the operator total (authoritative)
    and ts_backfill/group_backfill calls are subtracted. Data fields are identifiers that are not grouping fields,
    keyword args, local variables or literals; each is mapped to its dataset (must be a single dataset for ATOM).
    Returns {'operators', 'operators_total', 'free_operators', 'fields', 'n_fields', 'datasets', 'single_dataset',
             'unknown_fields', 'ok', 'issues'}."""
    c = client or get_client()
    platform_total = None
    if alpha is None and alpha_id:
        from .alphas import get_alpha

        alpha = get_alpha(alpha_id, c)
    if alpha is not None:
        reg = alpha.get("regular")
        expression = reg.get("code") if isinstance(reg, dict) else reg
        platform_total = reg.get("operatorCount") if isinstance(reg, dict) else None
        st = alpha.get("settings") or {}
        region, delay, universe = region or st.get("region"), delay if delay is not None else st.get("delay"), \
            universe or st.get("universe")
    if not expression:
        raise ValueError("expression or alpha required")
    cnt = operator_count(expression)
    total = platform_total if isinstance(platform_total, int) else cnt["total"]
    ops = total - cnt["free"]
    info = analyze_expression(expression)
    fields = sorted(f for f in info["identifiers"] if f not in GROUPING_FIELDS)
    datasets: Dict[str, Optional[str]] = {}
    if resolve_datasets and fields:
        datasets = field_datasets(fields, region or "USA", delay if delay is not None else 1, universe or "TOP3000", c)
    ds_set = sorted({d for d in datasets.values() if d})
    unknown = [f for f, d in datasets.items() if d is None]
    issues = []
    if ops > PP_MAX_OPERATORS:
        issues.append(f"{ops} operators > {PP_MAX_OPERATORS}")
    if len(fields) > PP_MAX_FIELDS:
        issues.append(f"{len(fields)} data fields > {PP_MAX_FIELDS}")
    if unknown:
        issues.append(f"not resolvable as data fields: {unknown}")
    return {
        "expression": expression, "operators": ops, "operators_total": total, "free_operators": cnt["free"],
        "operator_count_source": "platform" if isinstance(platform_total, int) else "local",
        "fields": fields, "n_fields": len(fields), "datasets": ds_set, "field_datasets": datasets,
        "single_dataset": len(ds_set) == 1 and not unknown, "unknown_fields": unknown,
        "ok": ops <= PP_MAX_OPERATORS and len(fields) <= PP_MAX_FIELDS and not unknown, "issues": issues,
    }


# ------------------------------------------------------------------ classification
def _is_perf_test(name: str) -> bool:
    return name.startswith(_PERF_PREFIXES)


def classify_alpha(alpha_id: str, client: BrainClient | None = None, check: Dict[str, Any] | None = None) -> Dict[str, Any]:
    """Classify a (FULL-mode) alpha with the official submission check.

    Categories (can combine): REGULAR, POWER_POOL, ATOM (estimated). Label examples: 'PP+REGULAR', 'PP+ATOM',
    'PURE_PP', 'REGULAR', 'NONE'.
      REGULAR    : every performance test PASS (a WARNING does not count: once a PP description is set the platform
                   downgrades failed regular tests to WARNING for pure-PP alphas).
      POWER_POOL : Sharpe >= 1, <= 8 ops, <= 3 fields, sub-universe / turnover / robust tests PASS,
                   self-correlation < 0.7, Power Pool correlation < 0.5.
      ATOM (est.): single dataset and every performance test PASS except the IS-ladder test (LOW_2Y_SHARPE).
    Also reports theme matches, description status, `submittable` (= check canSubmit) and blocking reasons.
    Note: correlation tests only compare against SUBMITTED alphas; re-classify after each submission."""
    c = client or get_client()
    from .alphas import check_submission, get_alpha

    alpha = get_alpha(alpha_id, c)
    chk = check or check_submission(alpha_id, client=c)
    checks = chk.get("checks") or []
    by = {}
    for x in checks:
        by.setdefault(x["name"], x)
    res = lambda n: (by.get(n) or {}).get("result")
    val = lambda n: (by.get(n) or {}).get("value")
    is_block = alpha.get("is") or {}
    sharpe = is_block.get("sharpe") or 0.0
    budget = pp_budget(alpha=alpha, client=c)

    perf = [x for x in checks if _is_perf_test(x["name"])]
    not_pass = [x["name"] for x in perf if x.get("result") in ("FAIL", "WARNING", "ERROR")]
    pending = [x["name"] for x in checks if x.get("result") == "PENDING"]
    regular = not not_pass and not pending

    pp_reasons: List[str] = []
    if sharpe < PP_MIN_SHARPE:
        pp_reasons.append(f"Sharpe {sharpe} < {PP_MIN_SHARPE}")
    pp_reasons += budget["issues"]
    for name in ("LOW_SUB_UNIVERSE_SHARPE", "LOW_TURNOVER", "HIGH_TURNOVER"):
        v, lim = val(name), (by.get(name) or {}).get("limit")
        bad = res(name) == "FAIL" or (isinstance(v, (int, float)) and isinstance(lim, (int, float)) and
                                      ((name != "HIGH_TURNOVER" and v < lim) or (name == "HIGH_TURNOVER" and v > lim)))
        if bad:
            pp_reasons.append(f"{name} {v} vs limit {lim}")
    for x in checks:
        if "ROBUST" in x["name"] and x.get("result") in ("FAIL", "WARNING"):
            pp_reasons.append(f"{x['name']} {x.get('value')}")
    sc = val("SELF_CORRELATION")
    if res("SELF_CORRELATION") == "FAIL" or (isinstance(sc, (int, float)) and sc >= 0.7):
        pp_reasons.append(f"self-correlation {sc}")
    ppc = val("POWER_POOL_CORRELATION")
    if res("POWER_POOL_CORRELATION") == "FAIL" or (isinstance(ppc, (int, float)) and ppc >= PP_MAX_PP_CORRELATION):
        pp_reasons.append(f"Power Pool correlation {ppc} >= {PP_MAX_PP_CORRELATION}")
    if pending:
        pp_reasons.append(f"checks pending: {pending}")
    power_pool = not pp_reasons

    atom_blockers = [n for n in not_pass if n != "LOW_2Y_SHARPE"]
    atom = budget["single_dataset"] and not atom_blockers and not pending

    themes_matched = [t.get("name") for x in checks if x["name"] == "MATCHES_THEMES" and x.get("result") == "PASS"
                      for t in x.get("themes") or []]
    pp_themes = [t for t in themes_matched if "Power Pool" in (t or "")]
    desc_missing = any(x["name"].startswith("POWER_POOL_DESCRIPTION") and x.get("result") in ("WARNING", "FAIL")
                       for x in checks)

    parts = (["PP"] if power_pool else []) + (["ATOM"] if atom else []) + (["REGULAR"] if regular else [])
    label = "+".join(parts) if parts else "NONE"
    if label == "PP":
        label = "PURE_PP"
    notes = []
    if power_pool and not regular and not atom:
        if desc_missing:
            notes.append("pure PP: set a description (>=100 chars, Idea/Rationale) before submitting")
        if not pp_themes:
            notes.append("pure PP must match an active Power Pool theme (none matched)")
        notes.append("uses the daily pure-Power-Pool quota")
    return {
        "alpha_id": alpha_id, "label": label, "regular": regular, "power_pool": power_pool, "atom_estimated": atom,
        "submittable": bool(chk.get("canSubmit")), "sharpe": sharpe, "fitness": is_block.get("fitness"),
        "turnover": is_block.get("turnover"), "self_correlation": sc, "pp_correlation": ppc,
        "prod_correlation": val("PROD_CORRELATION"), "budget": {k: budget[k] for k in
                                                                 ("operators", "operators_total", "n_fields", "fields", "datasets", "single_dataset")},
        "regular_blockers": not_pass, "pp_blockers": pp_reasons, "atom_blockers": atom_blockers,
        "themes_matched": themes_matched, "pp_themes_matched": pp_themes, "description_missing": desc_missing,
        "platform_classifications": [x.get("name") for x in alpha.get("classifications") or []],
        "notes": notes, "check_error": chk.get("error"),
    }


def classify_many(alpha_ids: Iterable[str], client: BrainClient | None = None) -> List[Dict[str, Any]]:
    """classify_alpha for several ids (sequential: the check endpoint is rate limited)."""
    return [classify_alpha(a, client) for a in dict.fromkeys(alpha_ids)]
