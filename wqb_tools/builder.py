"""(5) signal screening with automatic sign handling + budget-aware combination builder, (6) parameter sweeps."""
from __future__ import annotations

import itertools
from typing import Any, Dict, Iterable, List, Optional, Sequence

from .pp import operator_count

from .runner import run_experiment

DEFAULT_TEMPLATES = {
    "level": "ts_backfill({t}, {bk})",
    "delta": "ts_delta(ts_backfill({t}, {bk}), {w})",
    "zscore": "ts_zscore(ts_backfill({t}, {bk}), {zw})",
}


def _signal_expr(inner: str, sign: int) -> str:
    return f"rank({'-' if sign < 0 else ''}{inner})"


def screen_fields(terms: Sequence[Any], tag: str, *, templates: Dict[str, str] | None = None, bk: int = 120, w: int = 63,
                  zw: int = 126, flip_threshold: float = 0.3, **run_kwargs: Any) -> List[Dict[str, Any]]:
    """Simulate every (term x template) as rank(inner); return signals sorted by |Sharpe|, each with
    {'term', 'template', 'inner', 'sign' (+1/-1: flipped when Sharpe <= -flip_threshold), 'expr' (signed), row metrics}.
    terms: field ids / 'vec_avg(x)' strings, or dicts with 'term' (as returned by scout.representative_fields)."""
    tpls = templates or DEFAULT_TEMPLATES
    plan = []
    for t in terms:
        term = t["term"] if isinstance(t, dict) else t
        for name, tpl in tpls.items():
            inner = tpl.format(t=term, bk=bk, w=w, zw=zw)
            plan.append((term, name, inner))
    rows = run_experiment([f"rank({inner})" for _, _, inner in plan], tag, **run_kwargs)
    by_expr = {r.get("expr"): r for r in rows}
    out = []
    for term, name, inner in plan:
        r = by_expr.get(f"rank({inner})") or {}
        s = r.get("sharpe")
        if s is None:
            continue
        sign = -1 if s <= -flip_threshold else 1
        out.append({**{k: r.get(k) for k in ("sharpe", "fitness", "turnover", "sub", "sub_lim", "test_sharpe",
                                               "sharpe_2y", "amer", "emea", "apac", "alpha_id")},
                    "abs_sharpe": abs(s), "signed_sharpe": round(s * sign, 2), "term": term, "template": name,
                    "inner": inner, "sign": sign,
                    "expr": _signal_expr(inner, sign)})
    return sorted(out, key=lambda x: -x["abs_sharpe"])


def _field_of(term: str) -> str:
    return term[len("vec_avg("):-1] if term.startswith("vec_avg(") else term


def build_combos(signals: Sequence[Dict[str, Any]], *, top: int = 6, sizes: Iterable[int] = (2, 3), max_fields: int = 3,
                 max_ops: int = 8, min_abs_sharpe: float = 0.4, distinct_fields: bool = True,
                 weights: Optional[Sequence[float]] = None, limit: int = 20) -> List[str]:
    """Rank-sum combinations of the strongest signals: sum of signed rank(inner) terms.
    Keeps combos within the Power Pool budget (<= max_fields unique fields, <= max_ops operators excl. backfills),
    optionally with distinct underlying fields. Ordered by the sum of component |Sharpe| (a cheap prior)."""
    pool = [s for s in signals if s["abs_sharpe"] >= min_abs_sharpe][:top]
    combos = []
    for k in sizes:
        for group in itertools.combinations(pool, k):
            fields = {_field_of(s["term"]) for s in group}
            if distinct_fields and len(fields) < k:
                continue
            if len(fields) > max_fields:
                continue
            parts = []
            for i, s in enumerate(group):
                wgt = (weights[i] if weights and i < len(weights) else 1)
                parts.append((f"{wgt} * " if wgt != 1 else "") + s["expr"])
            expr = " + ".join(parts)
            if operator_count(expr)["pp"] > max_ops:
                continue
            combos.append((sum(s["abs_sharpe"] for s in group), expr))
    seen, out = set(), []
    for _, e in sorted(combos, key=lambda x: -x[0]):
        if e not in seen:
            seen.add(e)
            out.append(e)
    return out[:limit]


def signal_correlations(signals: Sequence[Dict[str, Any]], years: float = 4.0, client: Any = None) -> Dict[str, Any]:
    """Local PnL correlation between screened signals, adjusted for their signs: screen_fields simulates rank(inner)
    and flips weak-negative signals afterwards, so the raw PnL of a flipped signal is the mirror image of the signal
    you will actually use. Returns {'pairs': [{'a', 'b' (signed exprs), 'corr'}] sorted by |corr|, 'matrix', 'exprs'}.
    Signals need 'alpha_id', 'expr' and 'sign' (as returned by screen_fields)."""
    from .corr import correlation_matrix

    sig = [s for s in signals if s.get("alpha_id")]
    raw = correlation_matrix([s["alpha_id"] for s in sig], years=years, client=client)
    pos = {aid: i for i, aid in enumerate(raw["ids"])}
    n = len(sig)
    m: List[List[Optional[float]]] = [[None] * n for _ in range(n)]
    for i, a in enumerate(sig):
        for j, b in enumerate(sig):
            v = raw["matrix"][pos[a["alpha_id"]]][pos[b["alpha_id"]]]
            m[i][j] = None if v is None else round(v * (a.get("sign") or 1) * (b.get("sign") or 1), 4)
    pairs = sorted(({"a": sig[i]["expr"], "b": sig[j]["expr"], "corr": m[i][j]} for i in range(n) for j in range(i + 1, n)
                    if m[i][j] is not None), key=lambda p: -abs(p["corr"]))
    return {"exprs": [s["expr"] for s in sig], "matrix": m, "pairs": pairs}


def sweep(expr: str, tag: str, grid: Dict[str, Sequence[Any]], **run_kwargs: Any) -> List[Dict[str, Any]]:
    """Cartesian parameter sweep of one expression, e.g. grid={'neutralization': [...], 'decay': [0, 4, 10]}.
    Returns rows sorted by Sharpe (best first)."""
    keys = list(grid)
    items = [(expr, dict(zip(keys, vals))) for vals in itertools.product(*(grid[k] for k in keys))]
    rows = run_experiment(items, tag, **run_kwargs)
    return sorted(rows, key=lambda r: -(r.get("sharpe") or -9))
