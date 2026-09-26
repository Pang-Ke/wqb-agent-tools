"""(1) experiment runner, (9) simulation-quota monitor, (10) ledger query.

    rows = run_experiment(["rank(x)", ("rank(y)", {"decay": 6})], tag="screen", region="GLB", universe="TOPDIV3000",
                          neutralization="STATISTICAL", mode="FULL")
    print(results_table(rows))
    find_tried(field="capm_beta_1y", min_sharpe=1)
"""
from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence

from .client import BrainClient, get_client
from .simulate import build_payload, normalize_settings, payload_hash, simulate_batch
from .utils import append_jsonl, read_jsonl


# ------------------------------------------------------------------ metrics row
def metrics_row(result: Dict[str, Any]) -> Dict[str, Any]:
    """Flatten a simulate()/simulate_batch() result into one comparable row (incl. check limits and GLB regions)."""
    a = result.get("alpha") or {}
    m = a.get("is") or {}
    checks = [c for grp in (a.get("checks") or {}).values() for c in grp if isinstance(c, dict)]
    by = {c["name"]: c for c in checks}
    status_of = {}
    for res, grp in (a.get("checks") or {}).items():
        for c in grp:
            status_of[c["name"] if isinstance(c, dict) else c] = res
    v = lambda n: (by.get(n) or {}).get("value")
    s = result.get("settings") or {}
    return {
        "alpha_id": result.get("alpha_id"), "status": result.get("status"), "expr": result.get("expression"),
        "region": s.get("region"), "universe": s.get("universe"), "delay": s.get("delay"),
        "neut": s.get("neutralization"), "decay": s.get("decay"), "trunc": s.get("truncation"), "mode": s.get("simulationMode"),
        "sharpe": m.get("sharpe"), "fitness": m.get("fitness"), "turnover": m.get("turnover"), "returns": m.get("returns"),
        "drawdown": m.get("drawdown"), "margin": m.get("margin"),
        "sub": v("LOW_SUB_UNIVERSE_SHARPE"), "sub_lim": (by.get("LOW_SUB_UNIVERSE_SHARPE") or {}).get("limit"),
        "amer": v("LOW_GLB_AMER_SHARPE"), "emea": v("LOW_GLB_EMEA_SHARPE"), "apac": v("LOW_GLB_APAC_SHARPE"),
        "sharpe_2y": v("LOW_2Y_SHARPE"), "test_sharpe": (a.get("test") or {}).get("sharpe"),
        "train_sharpe": (a.get("train") or {}).get("sharpe"),
        "fails": [n for n, r in status_of.items() if r == "FAIL"],
        "message": (result.get("message") or "")[:160],
    }


def results_table(rows: Sequence[Dict[str, Any]], sort: str = "abs_sharpe", limit: int | None = None) -> str:
    key = (lambda x: -abs(x.get("sharpe") or 0)) if sort == "abs_sharpe" else (lambda x: -(x.get(sort) or -9))
    f = lambda v, p=2: f"{v:.{p}f}" if isinstance(v, (int, float)) else "-"
    lines = [f"{'sharpe':>7}{'fit':>6}{'tvr':>6}{'ret':>7}{'sub':>6}{'lim':>5}{'2y':>6}{'test':>6}{'AMER':>6}{'EMEA':>6}"
             f"{'APAC':>6} {'neut':<12}{'dcy':>3} {'alpha':<9} expr"]
    for x in sorted(rows, key=key)[:limit]:
        lines.append(f"{f(x.get('sharpe')):>7}{f(x.get('fitness')):>6}{f(x.get('turnover')):>6}{f(x.get('returns'), 3):>7}"
                     f"{f(x.get('sub')):>6}{f(x.get('sub_lim')):>5}{f(x.get('sharpe_2y')):>6}{f(x.get('test_sharpe')):>6}"
                     f"{f(x.get('amer')):>6}{f(x.get('emea')):>6}{f(x.get('apac')):>6} {str(x.get('neut'))[:12]:<12}"
                     f"{str(x.get('decay')):>3} {str(x.get('alpha_id')):<9} {x.get('expr')}"
                     + (f"   !! {x['message']}" if x.get("message") and not x.get("sharpe") else ""))
    return "\n".join(lines)


# ------------------------------------------------------------------ quota monitor (9)
def simulation_quota(client: BrainClient | None = None) -> Dict[str, Any]:
    """Daily simulation quota: last seen x-ratelimit headers (from POST /simulations) + today's activity count."""
    c = client or get_client()
    rl = dict(c.last_ratelimit or {})
    out = {"limit": rl.get("x-ratelimit-limit"), "remaining": rl.get("x-ratelimit-remaining"),
           "reset_seconds": rl.get("x-ratelimit-reset")}
    try:
        from .account import activity

        act = activity("simulations", client=c)
        out["yesterday"] = (act.get("yesterday") or {}).get("value")
        rows = act.get("rows") or []
        out["last_day"] = rows[-1] if rows else None
    except Exception:  # noqa: BLE001
        pass
    return out


# ------------------------------------------------------------------ ledger (10)
class Ledger:
    """Append-only JSONL log of every simulation (+ reuse of identical past runs)."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def rows(self) -> List[Dict[str, Any]]:
        return read_jsonl(self.path)

    def append(self, row: Dict[str, Any]) -> None:
        append_jsonl(self.path, row)

    def by_hash(self) -> Dict[str, Dict[str, Any]]:
        return {r["hash"]: r for r in self.rows() if r.get("hash") and r.get("status") in ("COMPLETE", "WARNING")}

    def find(self, text: str | None = None, field: str | None = None, tag: str | None = None,
             min_sharpe: float | None = None, region: str | None = None, universe: str | None = None,
             status_ok: bool = True) -> List[Dict[str, Any]]:
        out = []
        for r in self.rows():
            e = r.get("expr") or ""
            if text and text not in e:
                continue
            if field and field not in e:
                continue
            if tag and r.get("tag") != tag:
                continue
            if region and (r.get("region") or ((r.get("raw") or {}).get("settings") or {}).get("region")) != region:
                continue
            if universe and (r.get("universe") or ((r.get("raw") or {}).get("settings") or {}).get("universe")) != universe:
                continue
            if status_ok and r.get("status") not in ("COMPLETE", "WARNING"):
                continue
            if min_sharpe is not None and abs(r.get("sharpe") or 0) < min_sharpe:
                continue
            out.append({k: r.get(k) for k in r if k != "raw"})
        return out


_DEFAULT_LEDGER: Ledger | None = None


def default_ledger(path: str | Path | None = None) -> Ledger:
    global _DEFAULT_LEDGER
    if path is not None or _DEFAULT_LEDGER is None:
        _DEFAULT_LEDGER = Ledger(path or (get_client().cache_dir / "ledger.jsonl"))
    return _DEFAULT_LEDGER


def find_tried(**filters: Any) -> List[Dict[str, Any]]:
    """Query the ledger: find_tried(field='capm_beta_1y', min_sharpe=1.0, region='GLB')."""
    return default_ledger().find(**filters)


# ------------------------------------------------------------------ runner (1)
def run_experiment(
    exprs: Iterable[Any],
    tag: str,
    *,
    region: str = "USA",
    delay: int = 1,
    universe: str = "TOP3000",
    mode: str = "FULL",
    concurrency: int = 4,
    validate: bool = True,
    pp_budget_check: bool = False,
    reuse: bool = True,
    min_remaining: int = 200,
    ledger: Ledger | None = None,
    verbose: bool = True,
    client: BrainClient | None = None,
    **settings: Any,
) -> List[Dict[str, Any]]:
    """Validate -> (optionally) PP-budget-check -> reuse identical past runs -> multi-simulate -> log -> rows.
    exprs: strings or (expression, {setting overrides}). Stops early if the daily quota falls below min_remaining."""
    from .validate import validate_expression
    from .pp import pp_budget

    c = client or get_client()
    led = ledger or default_ledger()
    past = led.by_hash() if reuse else {}
    items, rows, skipped = [], [], []
    for e in exprs:
        expr, extra = e if isinstance(e, tuple) else (e, {})
        st = {"region": region, "delay": delay, "universe": universe, **settings, **extra}
        payload = build_payload(expr, mode=mode, **st)
        h = payload_hash(payload)
        if h in past:
            rows.append({**past[h], "reused": True})
            continue
        if validate:
            v = validate_expression(expr, st["region"], st["delay"], st["universe"], client=c)
            if not v["ok"]:
                skipped.append({"expr": expr, "reason": v["errors"][:2]})
                continue
        if pp_budget_check:
            b = pp_budget(expr, region=st["region"], delay=st["delay"], universe=st["universe"], client=c)
            if not b["ok"]:
                skipped.append({"expr": expr, "reason": b["issues"]})
                continue
        items.append((payload, h))
    q = simulation_quota(c)
    if q.get("remaining") is not None and int(q["remaining"]) < min_remaining + len(items):
        raise RuntimeError(f"simulation quota low: {q['remaining']} remaining, {len(items)} requested")
    if verbose:
        print(f"[{tag}] {len(items)} to simulate, {len(rows)} reused, {len(skipped)} skipped", file=sys.stderr, flush=True)
        for s in skipped:
            print(f"   skip: {s['expr'][:90]} -> {s['reason']}", file=sys.stderr)
    if items:
        results = simulate_batch([p for p, _ in items], concurrency=concurrency, use_cache=False, client=c,
                                 on_result=(lambda i, r: print(f"   {i}: {r['status']} "
                                                               f"{((r.get('alpha') or {}).get('is') or {}).get('sharpe')}",
                                                               file=sys.stderr, flush=True)) if verbose else None)
        ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
        for (payload, h), r in zip(items, results):
            row = {**metrics_row(r), "tag": tag, "hash": h, "time": ts, "raw": r}
            led.append(row)
            rows.append(row)
    return rows
