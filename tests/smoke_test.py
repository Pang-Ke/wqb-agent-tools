"""Live smoke test of every toolkit function against the BRAIN API.

    python agent_tools/tests/smoke_test.py              # read-only endpoints (no simulation quota used)
    python agent_tools/tests/smoke_test.py --simulate   # + QUICK/FULL/multi/cancel/region-agnostic/promote (~10 sims)
    python agent_tools/tests/smoke_test.py --mutate     # + reversible writes (temp alpha list, alpha name set/reset)

Submission (submit_alpha) is never exercised automatically because it is irreversible.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import wqb_tools as W  # noqa: E402

RESULTS = []


def step(name, fn, check=lambda r: r is not None):
    t0 = time.time()
    try:
        r = fn()
        ok = bool(check(r))
        note = _brief(r)
    except Exception as exc:  # noqa: BLE001
        r, ok, note = None, False, f"{type(exc).__name__}: {exc}"[:300]
        if "-v" in sys.argv:
            traceback.print_exc()
    dt = time.time() - t0
    RESULTS.append({"name": name, "ok": ok, "seconds": round(dt, 1), "note": note})
    print(f"{'PASS' if ok else 'FAIL'} {name:<38} {dt:6.1f}s  {note}", flush=True)
    return r


def _brief(r):
    if isinstance(r, list):
        return f"list[{len(r)}]"
    if isinstance(r, dict):
        keys = list(r.keys())[:6]
        return "dict{" + ",".join(map(str, keys)) + "}"
    if isinstance(r, str):
        return f"str[{len(r)}]"
    return str(r)[:80]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--simulate", action="store_true")
    ap.add_argument("--mutate", action="store_true")
    ap.add_argument("-v", action="store_true")
    a = ap.parse_args()

    # ---------------- auth / meta
    info = step("login", lambda: W.login(), lambda r: r.get("user", {}).get("id"))
    step("whoami", W.whoami, lambda r: "permissions" in r)
    step("me", W.me, lambda r: r.get("id"))
    step("permissions", W.permissions, lambda r: isinstance(r, list))
    opts = step("simulation_options", W.simulation_options, lambda r: "USA" in r["regions"])
    step("list_regions", W.list_regions, lambda r: "TOP3000" in r["USA"]["universes"])
    step("validate_settings(bad universe)", lambda: W.validate_settings({**W.DEFAULT_SETTINGS, "universe": "TOP9"}),
         lambda r: len(r) == 1)
    step("account_simulation_defaults", W.account_simulation_defaults, lambda r: "region" in r)
    ops = step("list_operators", lambda: W.list_operators(use_cache=False), lambda r: len(r) > 50)
    step("list_operators(category)", lambda: W.list_operators(category="Time Series"), lambda r: len(r) > 5)
    step("get_operator_doc(ts_mean)", lambda: W.get_operator_doc("ts_mean"), lambda r: "ts_mean" in r)

    # ---------------- data
    step("data_categories", W.data_categories, lambda r: len(r) > 3)
    ds = step("list_datasets", lambda: W.list_datasets(limit=60), lambda r: len(r) == 60)
    step("list_datasets(category,order)", lambda: W.list_datasets(category="analyst", order="-valueScore", limit=5),
         lambda r: all(d["category"]["id"] == "analyst" for d in r))
    step("get_dataset(pv1)", lambda: W.get_dataset("pv1", "USA", 1, "TOP3000"), lambda r: r.get("id") == "pv1")
    step("search_datasets", lambda: W.search_datasets("earnings surprise"), lambda r: isinstance(r, dict))
    step("list_datafields(pv1 all)", lambda: W.list_datafields(dataset_id="pv1", limit=None), lambda r: len(r) > 10)
    step("list_datafields(search)", lambda: W.list_datafields(search="implied volatility", limit=5), lambda r: len(r) == 5)
    step("list_datafields(type=VECTOR)", lambda: W.list_datafields(field_type="VECTOR", limit=5),
         lambda r: len(r) > 0 and all(f["type"] == "VECTOR" for f in r))
    step("get_datafield(close)", lambda: W.get_datafield("close", "USA", 1, "TOP3000"), lambda r: r.get("id") == "close")
    step("all_datafield_ids", W.all_datafield_ids, lambda r: "close" in r)
    step("dataset_fields_table(pv1)", lambda: W.dataset_fields_table("pv1"), lambda r: len(r) > 10)

    # ---------------- alphas (read)
    step("alphas_count_summary", W.alphas_count_summary, lambda r: "is" in r)
    lst = step("list_alphas", lambda: W.list_alphas(limit=3), lambda r: len(r["alphas"]) > 0)
    step("list_alphas(filters)", lambda: W.list_alphas(["is.sharpe>=1.25", "settings.region=USA"], order="-is.sharpe", limit=3),
         lambda r: all((x["is"] or {}).get("sharpe", 0) >= 1.25 for x in r["alphas"]))
    sub = W.list_alphas(stage="OS", limit=1)["alphas"]
    recent = W.list_alphas(status="UNSUBMITTED", limit=30)["alphas"]
    full = [x for x in recent if x["settings"].get("simulationMode") != "QUICK"]
    quick = [x for x in recent if x["settings"].get("simulationMode") == "QUICK"]
    aid = full[0]["id"] if full else None
    if quick:
        step("check_submission(QUICK -> refused)", lambda: W.check_submission(quick[0]["id"]),
             lambda r: r["canSubmit"] is False and r.get("error"))
    if aid:
        step("get_alpha", lambda: W.get_alpha(aid), lambda r: r.get("id") == aid)
        step("list_recordsets", lambda: W.list_recordsets(aid), lambda r: len(r) > 0)
        step("get_pnl", lambda: W.get_pnl(aid), lambda r: len(r) > 100)
        step("get_yearly_stats", lambda: W.get_yearly_stats(aid), lambda r: len(r) > 3)
        step("get_daily_pnl", lambda: W.get_daily_pnl(aid), lambda r: len(r) > 100)
        step("check_submission", lambda: W.check_submission(aid), lambda r: len(r["checks"]) > 0)
        step("get_correlations(self)", lambda: W.get_correlations(aid, "self"), lambda r: "rows" in r)
        comps = W.competitions(mine=True)
        if comps:
            step("before_after_performance(comp)", lambda: W.before_after_performance(aid, competition=comps[0]["id"]),
                 lambda r: "stats" in r)
    if sub:
        step("get_correlations(prod)", lambda: W.get_correlations(sub[0]["id"], "prod"), lambda r: len(r["rows"]) > 0)
    step("list_tags", W.list_tags, lambda r: isinstance(r, list))

    # ---------------- account / community
    step("activity(simulations)", lambda: W.simulation_counts(7), lambda r: "rows" in r or "total" in r)
    step("activity(submissions)", lambda: W.activity("submissions"), lambda r: isinstance(r, dict))
    step("activity(base-payment)", lambda: W.activity("base-payment"), lambda r: isinstance(r, dict))
    step("diversity", W.diversity, lambda r: "alphas" in r)
    step("pyramid_overview", W.pyramid_overview, lambda r: len(r) > 5)
    step("streak", W.streak, lambda r: "records" in r)
    step("achievements", W.achievements, lambda r: isinstance(r, list))
    step("consultant_summary", W.consultant_summary, lambda r: isinstance(r, dict))
    step("osmosis_summary", W.osmosis_summary, lambda r: isinstance(r, dict))
    step("messages", lambda: W.messages(limit=3), lambda r: len(r) > 0)
    step("messages_summary", W.messages_summary, lambda r: isinstance(r, dict))
    step("teams", W.teams, lambda r: isinstance(r, list))
    comps_all = step("competitions", W.competitions, lambda r: isinstance(r, list))
    if comps_all:
        cid = comps_all[0]["id"]
        step("competition", lambda: W.competition(cid), lambda r: r.get("id") == cid)
        step("competition_board", lambda: W.competition_board(cid, limit=3), lambda r: "results" in r)
    step("consultant_board(genius)", lambda: W.consultant_board("genius", limit=3), lambda r: "results" in r)
    step("consultant_board(leader)", lambda: W.consultant_board("leader", limit=3), lambda r: "results" in r)
    step("leaderboard_row(self)", W.leaderboard_row, lambda r: r is not None and "valueFactor" in r)
    step("leaderboard_row(unknown user)", lambda: W.leaderboard_row("ZZ00000") is None, lambda r: r is True)
    step("value_factor", W.value_factor, lambda r: "value_factor" in r and "weight_factor" in r)
    step("recent_submissions", lambda: W.recent_submissions(days=30), lambda r: isinstance(r, list))
    step("submission_days", W.submission_days, lambda r: {"count", "shortfall", "at_risk"} <= set(r))
    step("account_status", W.account_status, lambda r: {"genius_level", "value_factor", "submission_days"} <= set(r))
    step("events", lambda: W.events(limit=3), lambda r: isinstance(r, list))
    step("user_profile", lambda: W.user_profile(info["user"]["id"]), lambda r: "id" in r)

    # ---------------- docs
    idx = step("docs_index", W.docs_index, lambda r: len(r) > 20)
    step("get_doc_page(brain-api)", lambda: W.get_doc_page("brain-api"), lambda r: "/simulations" in r)
    step("search_docs", lambda: W.search_docs("neutralization"), lambda r: isinstance(r, dict))
    step("example_alphas", lambda: W.example_alphas(5), lambda r: len(r) > 0)
    step("video_courses", W.video_courses, lambda r: len(r) > 0)

    # ---------------- forum
    fo = W.get_forum()
    step("forum.login (SSO)", fo.login, lambda r: r.get("id"))
    step("forum.topics", fo.topics, lambda r: len(r) > 3)
    posts = step("forum.posts(CN topic)", lambda: fo.posts(W.CN_CONSULTANT_TOPIC, limit=5), lambda r: len(r) == 5)
    step("forum.posts(all, votes)", lambda: fo.posts(sort_by="votes", limit=3), lambda r: len(r) == 3)
    if posts:
        step("forum.post(+comments)", lambda: fo.post(posts[0]["id"]), lambda r: "body" in r)
    step("forum.search_posts", lambda: fo.search_posts("quick mode", limit=3), lambda r: len(r) > 0)
    step("forum.search_articles", lambda: fo.search_articles("self correlation", limit=3), lambda r: len(r) > 0)
    step("forum.article(ACE lib)", lambda: fo.article(30469668943767), lambda r: r.get("title"))
    step("forum.categories", fo.categories, lambda r: len(r) > 0)
    step("forum.sections", fo.sections, lambda r: len(r) > 0)
    step("forum.articles", lambda: fo.articles(limit=3), lambda r: len(r) == 3)

    # ---------------- Power Pool / local correlation (read-only)
    step("operator_count", lambda: W.operator_count("rank(-ts_backfill(close, 20)) + rank(vwap)"),
         lambda r: r == {"total": 5, "free": 1, "pp": 4})
    if aid:
        step("pp_budget(alpha)", lambda: W.pp_budget(alpha_id=aid), lambda r: "operators" in r and r["operator_count_source"] == "platform")
        step("classify_alpha", lambda: W.classify_alpha(aid), lambda r: r["label"] in
             {"PURE_PP", "PP+ATOM", "PP+REGULAR", "PP+ATOM+REGULAR", "REGULAR", "ATOM", "ATOM+REGULAR", "NONE"})
        step("get_correlations(power-pool)", lambda: W.get_correlations(aid, "power-pool"), lambda r: "rows" in r)
        step("self_correlation(local)", lambda: W.self_correlation(aid), lambda r: "max" in r)
        if lst and len(lst["alphas"]) > 1:
            step("correlation_matrix", lambda: W.correlation_matrix([aid, lst["alphas"][1]["id"]]), lambda r: len(r["matrix"]) == 2)

    # ---------------- research workflow tools (read-only)
    step("scout_datasets", lambda: W.scout_datasets("GLB", 1, "TOPDIV3000", top=3), lambda r: len(r) == 3)
    step("representative_fields", lambda: W.representative_fields("pv1", "USA", 1, "TOP3000", n=4), lambda r: len(r) > 0)
    step("simulation_quota", W.simulation_quota, lambda r: isinstance(r, dict))
    step("find_tried", lambda: W.find_tried(field="close"), lambda r: isinstance(r, list))
    if aid:
        step("robustness_report", lambda: W.robustness_report(aid), lambda r: "quality_score" in r)
        step("active_rules", lambda: W.active_rules(aid), lambda r: "limits" in r)

    # ---------------- local expression tools
    step("check_expression(ok)", lambda: W.check_expression("rank(ts_mean(close, 5))"), lambda r: r["ok"])
    step("check_expression(bad)", lambda: W.check_expression("rank(ts_meen(close, 5)"), lambda r: not r["ok"])
    step("validate_expression(ok)", lambda: W.validate_expression("rank(ts_mean(close, 5))"), lambda r: r["ok"])
    step("validate_expression(bad)", lambda: W.validate_expression("ts_mean(close, volume)"),
         lambda r: not r["ok"] and "constant" in r["errors"][0])
    step("expand_template", lambda: W.expand_template("ts_mean(<f/>, <d/>)", {"f": ["close", "vwap"], "d": [5, 20]}),
         lambda r: len(r) == 4)

    # ---------------- simulations (uses quota)
    if a.simulate:
        q = step("simulate QUICK", lambda: W.simulate("rank(-ts_delta(close, 4))", mode="QUICK", use_cache=False),
                 lambda r: r["ok"] and r["alpha"]["settings"]["simulationMode"] == "QUICK")
        step("simulate cache hit", lambda: W.simulate("rank(-ts_delta(close, 4))", mode="QUICK"),
             lambda r: r.get("cached"))
        step("simulate ERROR path", lambda: W.simulate("rank(unknown_field_zzz)", mode="QUICK", use_cache=False),
             lambda r: not r["ok"] and "unknown" in (r.get("message") or "").lower())
        step("simulate validate (bad)", lambda: W.simulate("rank(close)", universe="TOP9", validate=True),
             lambda r: r["status"] == "INVALID_SETTINGS")
        step("simulate_batch multi (3, QUICK)",
             lambda: W.simulate_batch(["rank(-ts_delta(vwap, 3))", "rank(-ts_delta(high, 3))", "rank(-ts_delta(low, 3))"],
                                      mode="QUICK", use_cache=False),
             lambda r: len(r) == 3 and all(x["ok"] and x.get("parent_simulation_id") for x in r))
        step("simulate no-wait + cancel", lambda: _cancel_test(), lambda r: r)
        step("simulate REGION_AGNOSTIC", lambda: W.simulate("rank(-ts_delta(close, 5))", alpha_type="REGION_AGNOSTIC",
                                                            mode="QUICK", use_cache=False, timeout=3600),
             lambda r: r["status"] in ("COMPLETE", "WARNING") or bool(r.get("message")))
        if q and q.get("alpha_id"):
            step("promote_to_full", lambda: W.promote_to_full(q["alpha_id"]),
                 lambda r: r["ok"] and r["alpha"]["settings"]["simulationMode"] == "FULL")

    # ---------------- reversible writes
    if a.mutate and aid:
        tag = step("create_tag", lambda: W.create_tag("agent_tools_smoke_tmp", [aid]), lambda r: r.get("id"))
        if tag and tag.get("id"):
            step("get_tag", lambda: W.get_tag(tag["id"]), lambda r: r.get("id") == tag["id"])
            step("update_tag(rename)", lambda: W.update_tag(tag["id"], rename="agent_tools_smoke_tmp2"), lambda r: True)
            step("delete_tag", lambda: W.delete_tag(tag["id"]), lambda r: r)
        before = W.get_alpha(aid).get("name")
        step("update_alpha(name)", lambda: W.update_alpha(aid, name="agent_tools_smoke"), lambda r: r.get("name") == "agent_tools_smoke")
        step("update_alpha(reset)", lambda: W.update_alpha(aid, name=before) if before else W.update_alpha(aid, clear=["name"]),
             lambda r: r.get("name") == before)

    passed = sum(r["ok"] for r in RESULTS)
    print(f"\n{passed}/{len(RESULTS)} passed")
    out = Path(__file__).resolve().parent / "smoke_report.json"
    out.write_text(json.dumps(RESULTS, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0 if passed == len(RESULTS) else 1


def _cancel_test():
    r = W.simulate("rank(ts_mean(volume, 9))", universe="TOP1000", wait=False, use_cache=False)
    return bool(r.get("simulation_id")) and W.cancel_simulation(r["simulation_id"])


if __name__ == "__main__":
    raise SystemExit(main())
