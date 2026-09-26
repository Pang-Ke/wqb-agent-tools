"""Test the expression validator:
  1) no false positives: expressions the platform actually simulated successfully must validate OK
  2) known-invalid expressions must be rejected with the right reason

    python tests/validate_expressions.py [path/to/ledger.jsonl]      (default: .cache/ledger.jsonl)
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import wqb_tools as W  # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
except Exception:
    pass

fails = 0

# 1) expressions that simulated OK on the platform: your experiment ledger (written by run_experiment, or a path you
#    pass) + your own submitted alphas
ledger = Path(sys.argv[1]) if len(sys.argv) > 1 else W.default_ledger().path
cases = {}
if ledger.exists():
    for line in ledger.read_text(encoding="utf-8").splitlines():
        r = json.loads(line)
        s = (r.get("raw") or {}).get("settings") or {"region": r.get("region"), "delay": r.get("delay"),
                                                     "universe": r.get("universe")}
        if r.get("status") in ("COMPLETE", "WARNING") and r.get("expr"):
            cases[(r["expr"], s.get("region"), s.get("delay"), s.get("universe"))] = True
for a in W.list_alphas(stage="OS", limit=None)["alphas"]:
    st = a["settings"]
    if a.get("expression"):
        cases[(a["expression"], st.get("region"), st.get("delay"), st.get("universe"))] = True
print(f"== {len(cases)} platform-valid expressions")
for expr, region, delay, universe in cases:
    r = W.validate_expression(expr, region or "USA", delay if delay is not None else 1, universe or "TOP3000")
    if not r["ok"]:
        fails += 1
        print(f"FALSE POSITIVE [{region}/{delay}/{universe}] {expr[:110]}\n    {r['errors']}")
print(f"   false positives: {fails}")

# 2) known-invalid expressions (GLB / D1 / TOPDIV3000 scope)
BAD = [
    ("rank(not_a_field_xyz)", "unknown variable"),
    ("rank(ts_meen(ts_backfill(capm_beta_1y, 20), 5))", "unknown operator"),
    ("ts_mean(capm_beta_1y, 5.5)", "positive integer"),
    ("ts_mean(capm_beta_1y, capm_beta_6m)", "constant number"),
    ("rank(ts_backfill(nws73_globalsent_finupscore, 20))", "vector field"),
    ("vec_avg(capm_beta_1y)", "VECTOR field"),
    ("group_rank(capm_beta_1y, capm_beta_6m)", "grouping field"),
    ("rank(capm_beta_1y", "expected ')'"),
    ("ts_mean(capm_beta_1y)", "missing argument"),
    ("rank(capm_beta_1y, foo=1)", "unknown keyword"),
    ("a = rank(capm_beta_1y);", "last statement"),
    ("ts_decay_linear(capm_beta_1y, 10, dense = 3)", "true/false"),
    ("rank(capm_beta_1y) +", "unexpected"),
]
bad_fail = 0
print("\n== known-invalid expressions")
for expr, why in BAD:
    r = W.validate_expression(expr, "GLB", 1, "TOPDIV3000")
    hit = (not r["ok"]) and any(why.lower() in e.lower() for e in r["errors"])
    bad_fail += not hit
    print(f"{'PASS' if hit else 'FAIL'} {expr:<60} -> {r['errors'][:1]}")

# 3) valid-but-tricky syntax
GOOD = [
    "a = ts_backfill(capm_beta_1y, 20); b = rank(-a); b",
    "capm_beta_1y > 1 ? rank(-capm_beta_1y) : 0",
    "group_neutralize(rank(capm_beta_1y), bucket(rank(capm_beta_6m), range=\"0, 1, 0.1\"))",
    "multiply(rank(capm_beta_1y), rank(capm_beta_6m), 2, filter=true)",
    "quantile(capm_beta_1y, driver = gaussian, sigma = 1.0)",
    "group_neutralize(rank(capm_beta_1y), group_cartesian_product(country, industry))",
    "rank(vec_avg(nws73_globalsent_finupscore)) /* comment */",
]
print("\n== valid tricky expressions")
good_fail = 0
for expr in GOOD:
    r = W.validate_expression(expr, "GLB", 1, "TOPDIV3000")
    good_fail += not r["ok"]
    print(f"{'PASS' if r['ok'] else 'FAIL'} {expr:<75} {r['errors'][:1]} {r['warnings'][:1]}")

total = fails + bad_fail + good_fail
print("\nALL PASS" if total == 0 else f"\n{total} FAILURES")
