"""Validate the Power Pool budget / classifier and local correlation against the platform's own numbers,
using alphas from YOUR account (picked automatically, or pass ids).

    python agent_tools/tests/validate_pp_corr.py [alpha ids ...]
No simulation quota is used (only reads and submission checks).
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import wqb_tools as W  # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
except Exception:
    pass

ok_all = True
LABELS = {"PURE_PP", "PP+ATOM", "PP+REGULAR", "PP+ATOM+REGULAR", "REGULAR", "ATOM", "ATOM+REGULAR", "NONE"}


def report(name, ok, detail=""):
    global ok_all
    ok_all &= bool(ok)
    print(f"{'PASS' if ok else 'FAIL'} {name:<58} {detail}")


# pick alphas from the account: submitted ones (for operator counts) and unsubmitted FULL-mode ones (for checks)
submitted = [a["id"] for a in W.list_alphas(stage="OS", limit=6)["alphas"]]
unsub = [a["id"] for a in W.list_alphas(status="UNSUBMITTED", limit=60)["alphas"]
         if a["settings"].get("simulationMode") != "QUICK"]
ids = sys.argv[1:] or (submitted + unsub)[:8]
print(f"using alphas: {ids}")

# 1) local operator count == platform operatorCount
for aid in ids:
    a = W.get_alpha(aid)
    code, plat = (a.get("regular") or {}).get("code"), (a.get("regular") or {}).get("operatorCount")
    if not code or plat is None:
        continue
    loc = W.operator_count(code)
    report(f"operator_count {aid}", loc["total"] == plat, f"local={loc['total']} platform={plat} pp_ops={loc['pp']}")

# 2) budget with dataset resolution (pv1 fields exist for every account)
b = W.pp_budget("rank(-ts_backfill(close, 20)) + rank(vwap)", region="USA", universe="TOP3000")
report("pp_budget: unary minus counted, backfill free, 1 dataset",
       b["operators"] == 4 and b["n_fields"] == 2 and b["datasets"] == ["pv1"],
       str({k: b[k] for k in ("operators", "operators_total", "n_fields", "datasets")}))
b = W.pp_budget("group_neutralize(rank(close), industry)", region="USA", universe="TOP3000")
report("pp_budget: grouping field not counted as data field", b["n_fields"] == 1, str(b["fields"]))

# 3) classifier + local vs platform correlation on unsubmitted FULL alphas
check_ids = [i for i in (sys.argv[1:] or unsub)][:3]
for aid in check_ids:
    c = W.classify_alpha(aid)
    report(f"classify {aid}", c["label"] in LABELS, f"label={c['label']} blockers={(c['pp_blockers'] or c['regular_blockers'])[:2]}")
    plat_self = W.get_correlations(aid, "self")["max"]
    loc_self = W.self_correlation(aid)
    if plat_self is not None and loc_self["max"] is not None:
        report(f"local self-corr {aid} ~ platform self", abs(loc_self["max"] - plat_self) < 0.02,
               f"local={loc_self['max']:.4f} platform={plat_self}")
    plat_pp = W.get_correlations(aid, "power-pool")["max"]
    loc_pp = W.power_pool_correlation(aid)
    if plat_pp is not None and loc_pp["max"] is not None:
        report(f"local PP-corr {aid} ~ platform power-pool", abs(loc_pp["max"] - plat_pp) < 0.02,
               f"local={loc_pp['max']:.4f} platform={plat_pp}")

if len(check_ids) >= 2:
    m = W.correlation_matrix(check_ids)
    report("correlation_matrix", len(m["matrix"]) == len(check_ids), [(p["a"], p["b"], round(p["corr"], 3)) for p in m["pairs"]])
    plan = W.plan_submission_order(check_ids, kind="power_pool")
    report("plan_submission_order", isinstance(plan["order"], list), plan["order"])
print("\nALL PASS" if ok_all else "\nSOME CHECKS FAILED")
