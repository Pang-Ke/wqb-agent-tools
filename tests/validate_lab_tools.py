"""Tests for the v1.2 research workflow tools (runner / scout / builder / quality / readiness).
Offline checks + read-only online checks (no simulation quota is used).

    python agent_tools/tests/validate_lab_tools.py
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import wqb_tools as W  # noqa: E402
from wqb_tools.simulate import build_payload, payload_hash  # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
except Exception:
    pass

ok_all = True


def check(name, cond, detail=""):
    global ok_all
    ok_all &= bool(cond)
    print(f"{'PASS' if cond else 'FAIL'} {name:<58} {str(detail)[:120]}")


# ---------------- offline
check("market-wide: commodity index", W.is_market_wide("Index value representing the price level of crude oil."))
check("market-wide: calendar regime", W.is_market_wide("Binary market regime label (e.g., risk-on/risk-off)."))
check("not market-wide: stock beta", not W.is_market_wide("Sensitivity coefficient of stock returns to bond yields."))
check("metadata: timestamp field", W.is_metadata("oth296_call_time") and W.is_metadata("anl39_curfperiodend"))
check("not metadata: model output", not W.is_metadata("confidence_bucket0_timeseries_calendar_5d"))

good = ("Idea: Firms with rising analyst estimates keep outperforming. Rationale for data used: the ARM score measures "
        "revisions. Rationale for operators used: rank scales the signal.")
check("description ok", W.check_description(good, "rank(arm)")["ok"])
check("description leaks expression", not W.check_description(good + " rank(arm)", "rank(arm)")["ok"])
check("description too short", not W.check_description("Idea: x", "rank(a)")["ok"])

sigs = [{"term": t, "expr": f"rank(ts_backfill({t}, 20))", "abs_sharpe": s} for t, s in
        (("fa", 1.2), ("fb", 1.1), ("fc", 0.9), ("fd", 0.8))]
combos = W.build_combos(sigs, sizes=(2, 3), max_ops=8)
check("build_combos respects budget", combos and all(W.operator_count(c)["pp"] <= 8 for c in combos), combos[:1])
check("build_combos max 3 fields", all(c.count("rank(") <= 3 for c in combos))

tmp = Path(tempfile.mkdtemp()) / "ledger.jsonl"
led = W.Ledger(tmp)
payload = build_payload("rank(close)", mode="FULL", region="USA", delay=1, universe="TOP3000")
led.append({"hash": payload_hash(payload), "status": "COMPLETE", "expr": "rank(close)", "sharpe": 0.5, "tag": "t",
            "region": "USA"})
check("ledger find", len(led.find(field="close", min_sharpe=0.4)) == 1)
rows = W.run_experiment(["rank(close)"], "t", region="USA", universe="TOP3000", mode="FULL", ledger=led, verbose=False)
check("run_experiment reuses identical past run (no simulation)", rows and rows[0].get("reused"), rows[0].get("sharpe"))

# ---------------- online, read-only
sc = W.scout_datasets("GLB", 1, "TOPDIV3000", top=5)
check("scout_datasets", len(sc) == 5 and "score" in sc[0], [s["id"] for s in sc])
reps = W.representative_fields("other296", "GLB", 1, "TOPDIV3000", n=6)
check("representative_fields drops metadata", reps and not any(W.is_metadata(r["representative"]) for r in reps),
      [r["term"] for r in reps])
q = W.simulation_quota()
check("simulation_quota", isinstance(q, dict), q)
lst = W.list_alphas(status="UNSUBMITTED", limit=40)["alphas"]
full = [a["id"] for a in lst if a["settings"].get("simulationMode") != "QUICK"][:2]
if full:
    rb = W.robustness_report(full[0])
    check("robustness_report", "quality_score" in rb and rb["yearly_sharpe"], {k: rb[k] for k in ("sharpe", "quality_score")})
    ru = W.active_rules(full[0])
    check("active_rules", "limits" in ru and ru["limits"].get("LOW_SHARPE"), ru["quotas"])
    rd = W.submission_readiness(full, purpose="power_pool")
    check("submission_readiness", "recommended_order" in rd, rd["recommended_order"])
print("\nALL PASS" if ok_all else "\nSOME CHECKS FAILED")
