"""Local PnL correlation (community method, matches the platform's self-correlation closely):

  daily return = pnl_t - pnl_{t-1}   (difference of the cumulative 'pnl' record set, NOT a percentage)
  window       = the most recent `years` (default 4) of each alpha's series
  zero returns are treated as missing; Pearson correlation on pairwise-complete days
  self-correlation = max correlation against your submitted (stage OS) alphas

Use it to (a) pre-screen candidates without spending check-submission calls, and (b) measure correlation
BETWEEN unsubmitted candidates, which the platform cannot do, to plan a submission order.
Pure standard library (no pandas/numpy).
"""
from __future__ import annotations

import json
import math
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from .client import BrainClient, get_client

Series = Dict[str, float]          # date (YYYY-MM-DD) -> daily pnl change


# ------------------------------------------------------------------ data
def pnl_series(alpha_id: str, client: BrainClient | None = None, use_cache: bool = True,
               cache_hours: float = 12.0) -> List[Tuple[str, float]]:
    """Cumulative PnL [(date, pnl)] from /alphas/{id}/recordsets/pnl (column 'pnl'), cached on disk."""
    c = client or get_client()
    cache_dir = c.cache_dir / "pnl"
    cache_dir.mkdir(exist_ok=True)
    path = cache_dir / f"{alpha_id}.json"
    if use_cache and path.exists() and time.time() - path.stat().st_mtime < cache_hours * 3600:
        try:
            return [tuple(x) for x in json.loads(path.read_text(encoding="utf-8"))]
        except ValueError:
            pass
    from .alphas import get_recordset

    raw = get_recordset(alpha_id, "pnl", client=c, raw=True)
    cols = [p.get("name") for p in (raw.get("schema") or {}).get("properties") or []]
    i_date, i_pnl = cols.index("date"), cols.index("pnl")
    rows = [(r[i_date], r[i_pnl]) for r in raw.get("records") or [] if r[i_pnl] is not None]
    path.write_text(json.dumps(rows), encoding="utf-8")
    return rows


def daily_returns(pnl: Sequence[Tuple[str, float]], years: float = 4.0) -> Series:
    """pnl_t - pnl_{t-1} over the last `years` of the series; zero changes dropped (treated as missing)."""
    if not pnl:
        return {}
    last = date.fromisoformat(pnl[-1][0][:10])
    cutoff = (last - timedelta(days=int(365.25 * years))).isoformat()
    out: Series = {}
    prev = None
    for d, v in pnl:
        if prev is not None and d[:10] > cutoff:
            r = v - prev
            if abs(r) > 1e-12:
                out[d[:10]] = r
        prev = v
    return out


def pearson(a: Series, b: Series, min_days: int = 60) -> Optional[float]:
    """Pearson correlation on the dates both series have. None if fewer than `min_days` common days."""
    common = a.keys() & b.keys()
    n = len(common)
    if n < min_days:
        return None
    xs = [a[d] for d in common]
    ys = [b[d] for d in common]
    mx, my = sum(xs) / n, sum(ys) / n
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    sxx = sum((x - mx) ** 2 for x in xs)
    syy = sum((y - my) ** 2 for y in ys)
    if sxx <= 0 or syy <= 0:
        return None
    return sxy / math.sqrt(sxx * syy)


def returns_for(alpha_ids: Iterable[str], years: float = 4.0, client: BrainClient | None = None,
                max_workers: int = 4) -> Dict[str, Series]:
    """Fetch PnL for many alphas in parallel and convert to daily returns."""
    c = client or get_client()
    ids = list(dict.fromkeys(alpha_ids))
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        pnls = list(ex.map(lambda i: pnl_series(i, c), ids))
    return {i: daily_returns(p, years) for i, p in zip(ids, pnls)}


# ------------------------------------------------------------------ correlations
def correlation(alpha_a: str, alpha_b: str, years: float = 4.0, client: BrainClient | None = None) -> Optional[float]:
    """Local PnL correlation of two alphas (submitted or not)."""
    r = returns_for([alpha_a, alpha_b], years, client)
    return pearson(r[alpha_a], r[alpha_b])


def correlation_matrix(alpha_ids: Sequence[str], years: float = 4.0, client: BrainClient | None = None) -> Dict[str, Any]:
    """Pairwise local PnL correlation matrix. Returns {'ids', 'matrix' (list of rows), 'pairs' (sorted high->low)}."""
    ids = list(dict.fromkeys(alpha_ids))
    r = returns_for(ids, years, client)
    m = [[1.0 if i == j else pearson(r[a], r[b]) for j, b in enumerate(ids)] for i, a in enumerate(ids)]
    pairs = sorted(({"a": ids[i], "b": ids[j], "corr": m[i][j]} for i in range(len(ids)) for j in range(i + 1, len(ids))
                    if m[i][j] is not None), key=lambda p: -p["corr"])
    return {"ids": ids, "matrix": m, "pairs": pairs}


def _class_ids(a: Dict[str, Any]) -> set:
    return {x.get("id") for x in a.get("classifications") or [] if isinstance(x, dict)}


def is_pure_power_pool(a: Dict[str, Any]) -> bool:
    """Submitted alpha classified Power Pool but not Regular (pure PP)."""
    ids = _class_ids(a)
    return "POWER_POOL:POWER_POOL_ELIGIBLE" in ids and "REGULAR:REGULAR" not in ids


def is_power_pool(a: Dict[str, Any]) -> bool:
    return "POWER_POOL:POWER_POOL_ELIGIBLE" in _class_ids(a) or "PowerPoolSelected" in (a.get("tags") or [])


def submitted_pool(client: BrainClient | None = None, region: str | None = None, kind: str = "regular",
                   power_pool_only: bool = False) -> List[Dict[str, Any]]:
    """Your submitted (OS) alphas that a given platform test compares against (verified against the API):
      kind='regular'    -> SELF_CORRELATION pool: submitted alphas except pure Power Pool ones
      kind='power_pool' -> POWER_POOL_CORRELATION pool: submitted Power Pool alphas
      kind='all'        -> every submitted alpha
    (power_pool_only=True is a legacy alias for kind='power_pool')."""
    from .alphas import list_alphas

    if power_pool_only:
        kind = "power_pool"
    rows = list_alphas(stage="OS", limit=None, order="-dateSubmitted", client=client)["alphas"]
    if region:
        rows = [a for a in rows if (a.get("settings") or {}).get("region") == region]
    if kind == "regular":
        rows = [a for a in rows if not is_pure_power_pool(a)]
    elif kind == "power_pool":
        rows = [a for a in rows if is_power_pool(a)]
    return rows


def power_pool_correlation(alpha_id: str, years: float = 4.0, top: int = 5,
                           client: BrainClient | None = None) -> Dict[str, Any]:
    """Local Power Pool correlation: max PnL correlation against your submitted Power Pool alphas of the same
    region (limit 0.5)."""
    return self_correlation(alpha_id, years=years, kind="power_pool", top=top, client=client)


def _alpha_region(alpha_id: str, client: BrainClient) -> Optional[str]:
    from .alphas import get_alpha

    return (get_alpha(alpha_id, client).get("settings") or {}).get("region")


def self_correlation(alpha_id: str, pool: Sequence[str] | None = None, years: float = 4.0, region: str | None = "auto",
                     power_pool_only: bool = False, top: int = 5, kind: str = "regular",
                     client: BrainClient | None = None) -> Dict[str, Any]:
    """Local self-correlation: max PnL correlation of `alpha_id` against `pool`.
    Default pool mirrors the platform (verified): submitted alphas of the SAME REGION (region='auto'), excluding pure
    Power Pool alphas for SELF_CORRELATION; kind='power_pool' uses the region's Power Pool alphas
    (POWER_POOL_CORRELATION). region=None compares against all regions. Returns {'max', 'max_with', 'top': [...]}."""
    c = client or get_client()
    if region == "auto":
        region = _alpha_region(alpha_id, c)
    if pool is None:
        pool = [a["id"] for a in submitted_pool(c, region, "power_pool" if power_pool_only else kind)]
    pool = [p for p in pool if p != alpha_id]
    r = returns_for([alpha_id, *pool], years, c)
    scores = [(p, pearson(r[alpha_id], r[p])) for p in pool]
    scores = sorted([s for s in scores if s[1] is not None], key=lambda s: -s[1])
    return {"alpha_id": alpha_id, "pool_size": len(pool), "max": scores[0][1] if scores else None,
            "max_with": scores[0][0] if scores else None, "top": [{"alpha_id": p, "corr": v} for p, v in scores[:top]]}


def plan_submission_order(candidates: Sequence[str], threshold: float | None = None, include_submitted: bool = True,
                          score: Dict[str, float] | None = None, years: float = 4.0, kind: str = "regular",
                          client: BrainClient | None = None) -> Dict[str, Any]:
    """Greedy submission plan: take candidates best-first (by `score`, default IS Sharpe) and keep one only if its
    local correlation to every already-kept candidate (and, optionally, the matching submitted pool) is < threshold.
    kind='regular'    -> pool = SELF_CORRELATION pool, default threshold 0.7
    kind='power_pool' -> pool = Power Pool alphas, default threshold 0.5 (pure Power Pool planning)"""
    c = client or get_client()
    from .alphas import get_alpha

    if threshold is None:
        threshold = 0.5 if kind == "power_pool" else 0.7
    info = {a: get_alpha(a, c) for a in candidates}
    if score is None:
        score = {a: ((info[a].get("is") or {}).get("sharpe") or 0.0) for a in candidates}
    region_of = {a: (info[a].get("settings") or {}).get("region") for a in candidates}
    pool_rows = submitted_pool(c, kind=kind) if include_submitted else []
    pool_region = {p["id"]: (p.get("settings") or {}).get("region") for p in pool_rows}
    r = returns_for([*candidates, *pool_region], years, c)
    kept, dropped = [], []
    for cand in sorted(candidates, key=lambda a: -score.get(a, 0.0)):
        # the platform only compares within a region
        others = [p for p, reg in pool_region.items() if reg == region_of[cand]] + \
                 [k for k in kept if region_of[k] == region_of[cand]]
        against = [(k, pearson(r[cand], r[k])) for k in others]
        worst = max((v for _, v in against if v is not None), default=None)
        blocker = next((k for k, v in against if v is not None and v == worst), None)
        if worst is None or worst < threshold:
            kept.append(cand)
        else:
            dropped.append({"alpha_id": cand, "corr": worst, "blocked_by": blocker})
    return {"order": kept, "dropped": dropped, "threshold": threshold, "pool_kind": kind, "score": score}
