"""(2) robustness report: is the Sharpe durable, recent and broad-based? (uses cached PnL; ~2 API calls per alpha)"""
from __future__ import annotations

import math
from datetime import date, timedelta
from typing import Any, Dict, List, Optional, Sequence

from .client import BrainClient, get_client


def _sharpe(xs: Sequence[float]) -> Optional[float]:
    xs = [x for x in xs if x is not None]
    if len(xs) < 20:
        return None
    m = sum(xs) / len(xs)
    sd = math.sqrt(sum((x - m) ** 2 for x in xs) / (len(xs) - 1))
    return None if sd == 0 else round(m / sd * math.sqrt(252), 2)


def robustness_report(alpha_id: str, client: BrainClient | None = None) -> Dict[str, Any]:
    """Durability diagnostics for a simulated alpha:
      yearly Sharpe (platform yearly-stats): share of positive years, worst year, dispersion
      recent Sharpe from daily PnL: last 1y / 2y (the 'is it still working?' check)
      test/train Sharpe ratio (test = held-out last testPeriod of IS), longest drawdown (days),
      investability-constrained / raw Sharpe ratio.
    flags + a 0-100 quality score (heuristic; higher is better)."""
    c = client or get_client()
    from .alphas import get_alpha, get_yearly_stats
    from .corr import pnl_series

    a = get_alpha(alpha_id, c)
    is_ = a.get("is") or {}
    pnl = pnl_series(alpha_id, c)
    rets = [(d[:10], v - pv) for (d, v), (_, pv) in zip(pnl[1:], pnl[:-1])]
    last = date.fromisoformat(rets[-1][0]) if rets else None
    recent = lambda yrs: _sharpe([r for d, r in rets if last and d > (last - timedelta(days=int(365.25 * yrs))).isoformat()])
    # longest drawdown duration (trading days from a peak until it is regained)
    peak, peak_i, longest = -1e30, 0, 0
    for i, (_, v) in enumerate(pnl):
        if v >= peak:
            longest = max(longest, i - peak_i)
            peak, peak_i = v, i
    longest = max(longest, len(pnl) - 1 - peak_i)
    years: List[Dict[str, Any]] = []
    try:
        # stages are TRAIN / TEST (in-sample split) or OS after submission; keep the in-sample years
        years = [y for y in get_yearly_stats(alpha_id, c) if y.get("stage") not in ("OS", "PROD")]
    except Exception:  # noqa: BLE001
        pass
    ys = [y.get("sharpe") for y in years if isinstance(y.get("sharpe"), (int, float))]
    pos_share = round(sum(s > 0 for s in ys) / len(ys), 2) if ys else None
    train, test = (a.get("train") or {}).get("sharpe"), (a.get("test") or {}).get("sharpe")
    ratio = round(test / train, 2) if isinstance(test, (int, float)) and train else None
    inv = ((is_.get("investabilityConstrained") or {}).get("sharpe"))
    inv_ratio = round(inv / is_["sharpe"], 2) if isinstance(inv, (int, float)) and is_.get("sharpe") else None
    r1, r2 = recent(1), recent(2)
    flags = []
    if ratio is not None and ratio < 0.3:
        flags.append(f"test/train Sharpe {ratio} < 0.3 (decaying or overfit)")
    if ratio is not None and ratio > 2.5:
        flags.append(f"test/train Sharpe {ratio} > 2.5 (in-sample weak)")
    if r1 is not None and r1 < 0:
        flags.append(f"last-1y Sharpe {r1} < 0")
    if pos_share is not None and pos_share < 0.6:
        flags.append(f"only {pos_share:.0%} positive years")
    if ys and min(ys) < -1.0:
        flags.append(f"worst year Sharpe {min(ys)}")
    if longest > 500:
        flags.append(f"longest drawdown {longest} trading days")
    if inv_ratio is not None and inv_ratio < 0.8:
        flags.append(f"investability-constrained keeps only {inv_ratio:.0%} of Sharpe")
    s = is_.get("sharpe") or 0
    score = (min(s, 2.5) / 2.5 * 35 + (pos_share or 0) * 20 + (min(max(r2 or 0, 0), 2.5) / 2.5) * 20
             + (min(max(ratio or 0, 0), 1.2) / 1.2) * 15 + (min(inv_ratio or 0, 1.0)) * 10)
    return {"alpha_id": alpha_id, "sharpe": s, "fitness": is_.get("fitness"), "turnover": is_.get("turnover"),
            "train_sharpe": train, "test_sharpe": test, "test_train_ratio": ratio, "sharpe_last_1y": r1,
            "sharpe_last_2y": r2, "positive_years": pos_share, "worst_year_sharpe": min(ys) if ys else None,
            "yearly_sharpe": {y.get("year"): y.get("sharpe") for y in years}, "longest_drawdown_days": longest,
            "investability_ratio": inv_ratio, "flags": flags, "quality_score": round(score, 1)}


def recent_strength(items: Sequence[Any], years: Optional[Sequence[int]] = None, workers: int = 6,
                    client: BrainClient | None = None) -> List[Dict[str, Any]]:
    """Rank alphas / screened signals by their Sharpe in the most recent in-sample years - the window the IS ladder
    test (IS_LADDER_SHARPE) checks first. Full-period Sharpe hides decay; a leg that is weak overall but strong in the
    last years is what fixes a ladder failure.
    items: alpha ids, or signal dicts with 'alpha_id' (+ optional 'sign' / 'expr', as returned by screen_fields;
    flipped signals get sign-adjusted Sharpes). years: default = the last 2 in-sample years of each alpha.
    Returns rows {alpha_id, expr, sign, yearly, recent (mean over `years`), years, test_sharpe}, best recent first."""
    from concurrent.futures import ThreadPoolExecutor

    from .alphas import get_alpha, get_yearly_stats

    c = client or get_client()
    sigs = [{"alpha_id": x} if isinstance(x, str) else x for x in items]

    def one(s: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        aid, sign = s.get("alpha_id"), (s.get("sign") or 1)
        if not aid:
            return None
        try:
            ys = {int(y["year"]): y["sharpe"] * sign for y in get_yearly_stats(aid, c)
                  if y.get("stage") not in ("OS", "PROD") and isinstance(y.get("sharpe"), (int, float))}
            test = ((get_alpha(aid, c).get("test") or {}).get("sharpe"))
        except Exception:  # noqa: BLE001
            return None
        win = list(years) if years else sorted(ys)[-2:]
        vals = [ys[y] for y in win if y in ys]
        return {"alpha_id": aid, "expr": s.get("expr"), "sign": sign, "yearly": ys, "years": win,
                "recent": round(sum(vals) / len(vals), 2) if vals else None,
                "test_sharpe": None if test is None else round(test * sign, 2)}

    with ThreadPoolExecutor(max(1, workers)) as ex:
        rows = [r for r in ex.map(one, sigs) if r]
    return sorted(rows, key=lambda r: -(r["recent"] if r["recent"] is not None else -9))


def compare_robustness(alpha_ids: Sequence[str], client: BrainClient | None = None) -> List[Dict[str, Any]]:
    """robustness_report for several alphas, best quality first."""
    return sorted((robustness_report(a, client) for a in dict.fromkeys(alpha_ids)), key=lambda r: -r["quality_score"])
