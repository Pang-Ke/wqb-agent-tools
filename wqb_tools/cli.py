"""Command line interface:  python agent_tools/wqb.py <command> [options]   (see --help / README.md)"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List

import importlib

W = importlib.import_module(__package__)  # this package's public API, whatever the folder is named
from .client import BrainError, PersonaRequired, get_client
from .utils import dump_json, to_csv

SETTING_FLAGS = {
    "region": str, "universe": str, "delay": int, "decay": int, "neutralization": str, "truncation": float,
    "pasteurization": str, "nan-handling": str, "unit-handling": str, "max-trade": str, "max-position": str,
    "test-period": str, "language": str, "lookback": int, "selection-handling": str, "selection-limit": int,
    "component-activation": str,
}


def _add_settings(p: argparse.ArgumentParser) -> None:
    g = p.add_argument_group("simulation settings (default: wqb_tools.DEFAULT_SETTINGS)")
    for flag, typ in SETTING_FLAGS.items():
        g.add_argument(f"--{flag}", type=typ, default=None)
    g.add_argument("--settings", help="JSON object of extra settings")
    g.add_argument("--quick", action="store_true", help="simulationMode=QUICK (fast, not directly submittable)")
    g.add_argument("--full", action="store_true", help="simulationMode=FULL")
    g.add_argument("--type", dest="alpha_type", default="REGULAR", help="REGULAR | REGION_AGNOSTIC | SUPER")
    g.add_argument("--visualization", action="store_true")


def _settings(a: argparse.Namespace) -> Dict[str, Any]:
    s: Dict[str, Any] = {}
    for flag in SETTING_FLAGS:
        v = getattr(a, flag.replace("-", "_"))
        if v is not None:
            s[flag.replace("-", "_")] = v
    if getattr(a, "settings", None):
        s.update(json.loads(a.settings))
    if getattr(a, "visualization", False):
        s["visualization"] = True
    return s


def _mode(a: argparse.Namespace) -> str | None:
    return "QUICK" if getattr(a, "quick", False) else ("FULL" if getattr(a, "full", False) else None)


def _add_scope(p: argparse.ArgumentParser) -> None:
    p.add_argument("--region", default="USA")
    p.add_argument("--delay", type=int, default=1)
    p.add_argument("--universe", default="TOP3000")
    p.add_argument("--instrument-type", default="EQUITY")


def _scope(a: argparse.Namespace) -> Dict[str, Any]:
    return {"region": a.region, "delay": a.delay, "universe": a.universe, "instrument_type": a.instrument_type}


def _read_items(path: str) -> List[Any]:
    text = Path(path).read_text(encoding="utf-8-sig").strip()
    if text.startswith("["):
        return json.loads(text)
    if path.endswith(".jsonl"):
        return [json.loads(line) for line in text.splitlines() if line.strip()]
    return [line.strip() for line in text.splitlines() if line.strip() and not line.strip().startswith("//")]


def build_parser() -> argparse.ArgumentParser:
    # global output flags, accepted before or after the command
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--out", default=argparse.SUPPRESS, help="write result to file (.json / .csv)")
    common.add_argument("--csv", action="store_true", default=argparse.SUPPRESS, help="print list results as CSV")
    common.add_argument("--compact", action="store_true", default=argparse.SUPPRESS, help="single-line JSON")
    common.add_argument("-v", "--verbose", action="store_true", default=argparse.SUPPRESS)
    ap = argparse.ArgumentParser(prog="wqb", description="WorldQuant BRAIN agent toolkit", parents=[common])
    sp = ap.add_subparsers(dest="cmd", required=True, metavar="command")

    def cmd(name: str, help_: str) -> argparse.ArgumentParser:
        return sp.add_parser(name, help=help_, description=help_, parents=[common])

    # auth / meta
    p = cmd("login", "authenticate (handles biometric 'persona' flow with --wait)")
    p.add_argument("--force", action="store_true")
    p.add_argument("--wait", action="store_true", help="if biometrics required: print URL and wait for Enter")
    cmd("whoami", "auth status: user id, token expiry, permissions")
    cmd("logout", "invalidate the session")
    p = cmd("options", "simulation setting options (regions/universes/delays/neutralizations/choices/ranges)")
    p.add_argument("--raw", action="store_true")
    cmd("regions", "region -> universes / delays / neutralizations")
    cmd("defaults", "account default simulation settings + toolkit defaults")
    cmd("permissions", "account permissions (QUICK_MODE, MULTI_SIMULATION, ...)")
    p = cmd("operators", "list operators")
    p.add_argument("--category")
    p.add_argument("--scope", help="REGULAR | COMBO | SELECTION")
    p.add_argument("--search")
    p.add_argument("--names", action="store_true", help="names only")
    p = cmd("op-doc", "long-form documentation of an operator")
    p.add_argument("name")

    # data
    cmd("categories", "data categories (with dataset/field/alpha counts)")
    p = cmd("datasets", "list datasets")
    _add_scope(p)
    p.add_argument("--category")
    p.add_argument("--search")
    p.add_argument("--order", help="e.g. -valueScore, -alphaCount, alphaCount")
    p.add_argument("--limit", type=int, default=50)
    p.add_argument("--all", action="store_true")
    p = cmd("dataset", "dataset details")
    p.add_argument("id")
    _add_scope(p)
    p = cmd("dataset-search", "semantic dataset search (Data Explorer)")
    p.add_argument("query")
    _add_scope(p)
    p = cmd("fields", "list data fields")
    _add_scope(p)
    p.add_argument("--dataset")
    p.add_argument("--search")
    p.add_argument("--type", dest="field_type", help="MATRIX | VECTOR | GROUP | UNIVERSE | SYMBOL")
    p.add_argument("--category")
    p.add_argument("--order", help="e.g. -alphaCount, -coverage")
    p.add_argument("--limit", type=int, default=100)
    p.add_argument("--all", action="store_true")
    p = cmd("field", "data field details")
    p.add_argument("id")
    _add_scope(p)
    cmd("field-ids", "ids of all data fields on the platform")
    p = cmd("visualize", "request a data-field visualization (async, shows on platform)")
    p.add_argument("id")
    _add_scope(p)

    # simulation
    p = cmd("simulate", "simulate one expression and return results")
    p.add_argument("expression")
    _add_settings(p)
    p.add_argument("--no-wait", action="store_true")
    p.add_argument("--no-cache", action="store_true", help="ignore the local duplicate cache")
    p.add_argument("--no-alpha", action="store_true", help="don't fetch alpha stats")
    p.add_argument("--validate", action="store_true", help="validate settings against OPTIONS first")
    p.add_argument("--combo")
    p.add_argument("--selection")
    p = cmd("payload", "print the simulation payload that would be sent (no API call)")
    p.add_argument("expression")
    _add_settings(p)
    p = cmd("batch", "simulate many expressions (file: .txt one per line | .json list | .jsonl)")
    p.add_argument("file")
    _add_settings(p)
    p.add_argument("--concurrency", type=int, default=3)
    p.add_argument("--no-multi", action="store_true", help="disable multi-simulation")
    p.add_argument("--multi-size", type=int, default=10)
    p.add_argument("--no-cache", action="store_true")
    p.add_argument("--no-alpha", action="store_true")
    p.add_argument("--jsonl", help="append each result to this .jsonl as it completes")
    p = cmd("sim-status", "one-shot simulation status")
    p.add_argument("id")
    p = cmd("sim-wait", "wait for a simulation to finish")
    p.add_argument("id")
    p = cmd("sim-cancel", "cancel a simulation")
    p.add_argument("id")
    p = cmd("promote", "re-simulate an alpha (e.g. QUICK) in FULL mode")
    p.add_argument("alpha_id")

    # alphas
    p = cmd("alpha", "alpha details (summary; --raw for full JSON)")
    p.add_argument("id")
    p.add_argument("--raw", action="store_true")
    p = cmd("alphas", "list your alphas; positional filters like 'is.sharpe>=1.5' 'settings.region=USA'")
    p.add_argument("filters", nargs="*")
    for f in ("status", "stage", "region", "universe", "type", "date-from", "date-to"):
        p.add_argument(f"--{f}")
    p.add_argument("--delay", type=int)
    p.add_argument("--sharpe-min", type=float)
    p.add_argument("--fitness-min", type=float)
    p.add_argument("--order", default="-dateCreated")
    p.add_argument("--limit", type=int, default=50)
    p.add_argument("--offset", type=int, default=0)
    p.add_argument("--all", action="store_true")
    p.add_argument("--hidden", action="store_true")
    p.add_argument("--raw", action="store_true")
    cmd("alpha-counts", "count of your alphas by stage (is/os/prod)")
    p = cmd("recordsets", "list record sets of an alpha")
    p.add_argument("id")
    p = cmd("recordset", "get a record set (pnl, sharpe, turnover, daily-pnl, yearly-stats, ...)")
    p.add_argument("id")
    p.add_argument("name")
    p = cmd("pnl", "cumulative PnL rows")
    p.add_argument("id")
    p = cmd("yearly", "yearly stats rows")
    p.add_argument("id")
    p = cmd("check", "run pre-submission checks (correlation, sub-universe, ...)")
    p.add_argument("id")
    p = cmd("corr", "platform correlation: self | prod | power-pool")
    p.add_argument("id")
    p.add_argument("--kind", default="self", choices=["self", "prod", "power-pool"])
    p = cmd("pp-budget", "Power Pool budget of an expression or alpha (ops excl. backfills, fields, datasets)")
    p.add_argument("expression", nargs="?")
    p.add_argument("--alpha", help="use a simulated alpha (platform operatorCount)")
    _add_scope(p)
    p = cmd("pp-classify", "classify alphas via the official check: PURE_PP / PP+ATOM / PP+REGULAR / REGULAR / NONE")
    p.add_argument("ids", nargs="+")
    p = cmd("corr-matrix", "local PnL correlation matrix between alphas (works for unsubmitted candidates)")
    p.add_argument("ids", nargs="+")
    p.add_argument("--years", type=float, default=4.0)
    p = cmd("self-corr-local", "local correlation vs your submitted alphas (default: SELF_CORRELATION pool)")
    p.add_argument("id")
    p.add_argument("--pp", action="store_true", help="Power Pool pool instead (mirrors POWER_POOL_CORRELATION)")
    p.add_argument("--region")
    p.add_argument("--years", type=float, default=4.0)
    p = cmd("submit-order", "greedy submission order so kept candidates stay below a correlation threshold")
    p.add_argument("ids", nargs="+")
    p.add_argument("--pp", action="store_true", help="plan pure Power Pool submissions (PP pool, threshold 0.5)")
    p.add_argument("--threshold", type=float, help="default 0.7 (regular) / 0.5 (--pp)")
    p.add_argument("--no-pool", action="store_true", help="ignore already-submitted alphas")
    p = cmd("before-after", "portfolio / competition performance before vs after adding the alpha")
    p.add_argument("id")
    p.add_argument("--competition")
    p.add_argument("--team")
    p = cmd("update-alpha", "set alpha properties")
    p.add_argument("id")
    p.add_argument("--name")
    p.add_argument("--color")
    p.add_argument("--tags", nargs="*")
    p.add_argument("--category")
    p.add_argument("--desc", help="regular description")
    p.add_argument("--favorite", action=argparse.BooleanOptionalAction, default=None)
    p.add_argument("--hidden", action=argparse.BooleanOptionalAction, default=None)
    p.add_argument("--clear", nargs="*", default=[], help="fields to reset to null, e.g. name color")
    p = cmd("submit", "SUBMIT an alpha (irreversible) - requires --yes")
    p.add_argument("id")
    p.add_argument("--yes", action="store_true")
    p = cmd("components", "component alphas of a SuperAlpha")
    p.add_argument("id")

    # tags
    cmd("tags", "your alpha lists / tags")
    p = cmd("tag", "tag details")
    p.add_argument("id")
    p = cmd("tag-create", "create alpha list")
    p.add_argument("name")
    p.add_argument("--alphas", nargs="*", default=[])
    p.add_argument("--kind", default="LIST", help="LIST | TAG | CATEGORY | COLOR")
    p = cmd("tag-update", "add/remove alphas, rename")
    p.add_argument("id")
    p.add_argument("--add", nargs="*")
    p.add_argument("--remove", nargs="*")
    p.add_argument("--rename")
    p = cmd("tag-delete", "delete a tag/list - requires --yes")
    p.add_argument("id")
    p.add_argument("--yes", action="store_true")
    p = cmd("tag-corr", "correlations of a list (inner | self)")
    p.add_argument("id")
    p.add_argument("--kind", default="inner", choices=["inner", "self"])

    # account
    cmd("me", "your profile")
    p = cmd("activity", "simulations | submissions | base-payment | other-payment | referrals")
    p.add_argument("name")
    p.add_argument("--from", dest="date_from", help="YYYY-MM-DD")
    p = cmd("diversity", "submitted alpha diversity by region/delay/category")
    p.add_argument("--grouping", default="region,delay,dataCategory")
    cmd("pyramids", "pyramid alpha counts joined with multipliers")
    cmd("streak", "simulation streak")
    cmd("achievements", "achievements")
    cmd("consultant", "consultant / genius summary")
    cmd("status", "one-call summary: genius level, quarter stats, value factor, submission days, today's submissions")
    p = cmd("vf", "value factor + weight factor from the consultant leaderboard")
    p.add_argument("--user", help="another user id (default: you)")
    p = cmd("sub-days", "distinct submission days in the rolling window vs the 20-day value-factor rule")
    p.add_argument("--window", type=int, default=91)
    p = cmd("submitted", "alphas you submitted recently (platform days, US Eastern)")
    p.add_argument("--days", type=int, default=7, help="1 = today only")
    p.add_argument("--since", help="YYYY-MM-DD (overrides --days)")
    p = cmd("genius-progress", "this quarter vs a Genius level: signals, complete pyramids (>= 3 alphas), gaps")
    p.add_argument("--level", default="EXPERT", choices=["EXPERT", "MASTER", "GRANDMASTER"])
    p.add_argument("--quarter", default="current", choices=["current", "previous"])
    p.add_argument("--candidates", nargs="*", default=[], help="unsubmitted alpha ids to add hypothetically (slow)")
    cmd("osmosis", "osmosis summary")
    cmd("osmosis-alloc", "your current Osmosis points by region (complete = 100,000 over >= 10 alphas)")
    p = cmd("osmosis-set", "set Osmosis points on submitted alphas: ID=POINTS ... (0 removes)")
    p.add_argument("pairs", nargs="+", help="e.g. AbCdEf12=15000 XyZ98765=0")
    p = cmd("messages", "announcements / notifications")
    p.add_argument("--type", choices=["ANNOUNCEMENT", "NOTIFICATION"])
    p.add_argument("--limit", type=int, default=20)
    cmd("teams", "your teams")
    p = cmd("competitions", "competitions")
    p.add_argument("--mine", action="store_true")
    p = cmd("competition", "competition details")
    p.add_argument("id")
    p = cmd("board", "competition leaderboard")
    p.add_argument("id")
    p.add_argument("--board", default="leader")
    p.add_argument("--limit", type=int, default=50)
    p.add_argument("--offset", type=int, default=0)
    p = cmd("genius", "consultant boards: genius | leader | power-pool | spc")
    p.add_argument("--board", default="genius")
    p.add_argument("--limit", type=int, default=50)
    p.add_argument("--offset", type=int, default=0)
    p = cmd("events", "webinars / events")
    p.add_argument("--upcoming", action="store_true")
    p.add_argument("--limit", type=int, default=50)

    # docs
    p = cmd("docs", "documentation index (or --search)")
    p.add_argument("--search")
    p = cmd("doc", "one documentation page as markdown")
    p.add_argument("page_id")
    p = cmd("docs-dump", "save all documentation pages as markdown")
    p.add_argument("dir")
    p = cmd("examples", "official example alphas")
    p.add_argument("--limit", type=int, default=50)
    cmd("videos", "video courses")

    # forum
    cmd("forum-topics", "community topics (sub-forums)")
    p = cmd("forum-posts", "latest forum posts")
    p.add_argument("--topic", type=int)
    p.add_argument("--sort", default="created_at", help="created_at | recent_activity | votes | comments")
    p.add_argument("--limit", type=int, default=30)
    p.add_argument("--full", action="store_true", help="don't truncate bodies")
    p = cmd("forum-post", "one post with comments")
    p.add_argument("id", type=int)
    p.add_argument("--no-comments", action="store_true")
    p = cmd("forum-search", "search community posts")
    p.add_argument("query")
    p.add_argument("--topic", type=int)
    p.add_argument("--limit", type=int, default=25)
    p = cmd("forum-crawl", "fetch newest posts of a topic (default: Chinese consultant forum) and save JSON")
    p.add_argument("--topic", type=int, default=W.CN_CONSULTANT_TOPIC)
    p.add_argument("--limit", type=int, default=50)
    p.add_argument("--since", type=int, help="only posts newer than this post id")
    p.add_argument("--dir", help="output directory")
    p.add_argument("--no-comments", action="store_true")
    p = cmd("article-search", "search help-center articles")
    p.add_argument("query")
    p.add_argument("--limit", type=int, default=25)
    p = cmd("article", "one help-center article")
    p.add_argument("id", type=int)
    p = cmd("articles", "list help-center articles")
    p.add_argument("--section", type=int)
    p.add_argument("--category", type=int)
    p.add_argument("--limit", type=int, default=50)
    cmd("help-categories", "help-center categories")
    p = cmd("help-sections", "help-center sections")
    p.add_argument("--category", type=int)

    # expressions / raw
    # research workflow (v1.2)
    p = cmd("scout", "rank datasets for a scope (power_pool ignores crowding, regular penalises it)")
    _add_scope(p)
    p.add_argument("--purpose", default="power_pool", choices=["power_pool", "regular"])
    p.add_argument("--exclude", nargs="*", default=[])
    p.add_argument("--top", type=int, default=30)
    p = cmd("rep-fields", "screening-ready representative fields of a dataset (dedup families, drop metadata/market-wide)")
    p.add_argument("dataset")
    _add_scope(p)
    p.add_argument("--n", type=int, default=16)
    p.add_argument("--keyword", help="regex on id + description")
    p = cmd("concepts", "distinct metrics of a dataset (field families with window/horizon variants collapsed)")
    p.add_argument("dataset")
    _add_scope(p)
    p = cmd("experiment", "validated, ledger-logged batch simulation (file: .txt/.json/.jsonl like 'batch')")
    p.add_argument("file")
    p.add_argument("--tag", required=True)
    _add_settings(p)
    p.add_argument("--concurrency", type=int, default=4)
    p.add_argument("--pp-budget", action="store_true", help="skip expressions over the Power Pool budget")
    p.add_argument("--no-reuse", action="store_true")
    p = cmd("tried", "query the experiment ledger")
    p.add_argument("--text")
    p.add_argument("--field")
    p.add_argument("--tag")
    p.add_argument("--min-sharpe", type=float)
    p.add_argument("--region")
    p = cmd("quota", "daily simulation quota (last seen rate-limit headers + today's count)")
    p = cmd("robustness", "durability report: yearly Sharpe, last 1y/2y, test/train, drawdown length, quality score")
    p.add_argument("ids", nargs="+")
    p = cmd("readiness", "what to submit and in which order (classification + robustness + local correlation)")
    p.add_argument("ids", nargs="+")
    p.add_argument("--regular", action="store_true", help="plan regular submissions instead of pure Power Pool")
    p.add_argument("--quota", type=int, help="submissions left today")
    p = cmd("pp-presubmit", "Power Pool pre-submission: set description from an idea, check, theme match, PP corr")
    p.add_argument("id")
    p.add_argument("--idea", help="economic hypothesis (drafts and sets the 3-part description); omit to keep the current one")
    p = cmd("rules", "active themes, quotas and test limits as seen by an unsubmitted alpha's check")
    p.add_argument("id")
    p = cmd("desc-check", "check a Power Pool description (length, sections, no expression, uniqueness)")
    p.add_argument("id", help="alpha id (its expression is used to detect leaks)")
    p.add_argument("--text", help="description text (default: the alpha's current description)")
    p = cmd("desc-draft", "draft a Power Pool description; you supply the idea")
    p.add_argument("id")
    p.add_argument("--idea", required=True)
    p = cmd("validate", "full pre-flight validation: syntax, operators/arity/kwargs, windows, field availability & types")
    p.add_argument("expression")
    _add_scope(p)
    p.add_argument("--no-fields", action="store_true", help="skip data-field lookups (offline)")
    p = cmd("lint", "quick local check (parens, operator names, optional field ids); see 'validate' for the full check")
    p.add_argument("expression")
    p.add_argument("--dataset", help="also validate identifiers against this dataset's fields")
    _add_scope(p)
    p = cmd("expand", "expand a template: --values '{\"f\":[\"close\",\"vwap\"],\"d\":[5,20]}'")
    p.add_argument("template")
    p.add_argument("--values", required=True)
    p = cmd("raw", "call any API endpoint: raw GET /users/self/alphas --params '{\"limit\":1}'")
    p.add_argument("method")
    p.add_argument("path")
    p.add_argument("--params")
    p.add_argument("--body")
    p.add_argument("--poll", action="store_true")
    return ap


def run(a: argparse.Namespace) -> Any:
    c = get_client()
    c.verbose = a.verbose
    f = W.get_forum
    cmd = a.cmd
    if cmd == "login":
        try:
            return c.authenticate(force=a.force)
        except PersonaRequired as exc:
            if not a.wait:
                return {"persona_required": True, "url": exc.url,
                        "hint": "open the URL, finish biometrics, then run: wqb.py login --wait (or complete_persona)"}
            print(f"Open this URL in your browser and complete biometric sign-in:\n{exc.url}", file=sys.stderr)
            input("Press Enter when done...")
            return c.complete_persona(exc.url)
    if cmd == "whoami":
        return W.whoami()
    if cmd == "logout":
        return {"logged_out": c.logout()}
    if cmd == "options":
        return W.raw_simulation_options() if a.raw else W.simulation_options()
    if cmd == "regions":
        return W.list_regions()
    if cmd == "defaults":
        return {"account": W.account_simulation_defaults(), "toolkit": W.DEFAULT_SETTINGS}
    if cmd == "permissions":
        return W.permissions()
    if cmd == "operators":
        ops = W.list_operators(category=a.category, scope=a.scope, search=a.search)
        return [o["name"] for o in ops] if a.names else ops
    if cmd == "op-doc":
        return W.get_operator_doc(a.name)
    # data
    if cmd == "categories":
        return W.data_categories()
    if cmd == "datasets":
        return W.list_datasets(a.region, a.delay, a.universe, instrument_type=a.instrument_type, category=a.category,
                               search=a.search, order=a.order, limit=None if a.all else a.limit)
    if cmd == "dataset":
        return W.get_dataset(a.id, **_scope(a))
    if cmd == "dataset-search":
        return W.search_datasets(a.query, **_scope(a))
    if cmd == "fields":
        return W.list_datafields(a.region, a.delay, a.universe, instrument_type=a.instrument_type, dataset_id=a.dataset,
                                 search=a.search, field_type=a.field_type, category=a.category, order=a.order,
                                 limit=None if a.all else a.limit)
    if cmd == "field":
        return W.get_datafield(a.id, **_scope(a))
    if cmd == "field-ids":
        return W.all_datafield_ids()
    if cmd == "visualize":
        return W.request_datafield_visualization(a.id, **_scope(a))
    # simulation
    if cmd == "payload":
        return W.build_payload(a.expression, alpha_type=a.alpha_type, mode=_mode(a), **_settings(a))
    if cmd == "simulate":
        payload = W.build_payload(a.expression if a.alpha_type.upper() != "SUPER" else None, alpha_type=a.alpha_type,
                                  mode=_mode(a), combo=a.combo, selection=a.selection, **_settings(a))
        return W.simulate(payload=payload, wait=not a.no_wait, use_cache=not a.no_cache,
                          fetch_alpha=not a.no_alpha, validate=a.validate)
    if cmd == "batch":
        items = _read_items(a.file)

        def progress(i: int, r: Dict[str, Any]) -> None:
            al = r.get("alpha") or {}
            m = al.get("is") or {}
            print(f"[{i}] {r.get('status')} {r.get('alpha_id') or ''} sharpe={m.get('sharpe')} fitness={m.get('fitness')} "
                  f"turnover={m.get('turnover')} {(r.get('message') or '')[:100]}", file=sys.stderr, flush=True)

        return W.simulate_batch(items, mode=_mode(a), concurrency=a.concurrency, multi=False if a.no_multi else None,
                                multi_size=a.multi_size, use_cache=not a.no_cache, fetch_alpha=not a.no_alpha,
                                out_jsonl=a.jsonl, on_result=progress, **_settings(a))
    if cmd == "sim-status":
        return W.get_simulation(a.id)
    if cmd == "sim-wait":
        return W.wait_simulation(a.id)
    if cmd == "sim-cancel":
        return {"cancelled": W.cancel_simulation(a.id)}
    if cmd == "promote":
        return W.promote_to_full(a.alpha_id)
    # alphas
    if cmd == "alpha":
        al = W.get_alpha(a.id)
        return al if a.raw else W.summarize_alpha(al)
    if cmd == "alphas":
        return W.list_alphas(a.filters, status=a.status, stage=a.stage, region=a.region, universe=a.universe,
                             delay=a.delay, alpha_type=a.type, date_from=a.date_from, date_to=a.date_to,
                             sharpe_min=a.sharpe_min, fitness_min=a.fitness_min, order=a.order,
                             hidden=True if a.hidden else None, limit=None if a.all else a.limit,
                             offset=a.offset, summary=not a.raw)
    if cmd == "alpha-counts":
        return W.alphas_count_summary()
    if cmd == "recordsets":
        return W.list_recordsets(a.id)
    if cmd == "recordset":
        return W.get_recordset(a.id, a.name)["rows"]
    if cmd == "pnl":
        return W.get_pnl(a.id)
    if cmd == "yearly":
        return W.get_yearly_stats(a.id)
    if cmd == "check":
        return W.check_submission(a.id)
    if cmd == "corr":
        return W.get_correlations(a.id, a.kind)
    if cmd == "pp-budget":
        if a.alpha:
            return W.pp_budget(alpha_id=a.alpha)
        return W.pp_budget(a.expression, region=a.region, delay=a.delay, universe=a.universe)
    if cmd == "pp-classify":
        return W.classify_many(a.ids)
    if cmd == "corr-matrix":
        return W.correlation_matrix(a.ids, a.years)
    if cmd == "self-corr-local":
        return W.self_correlation(a.id, years=a.years, region=a.region or "auto", kind="power_pool" if a.pp else "regular")
    if cmd == "submit-order":
        return W.plan_submission_order(a.ids, threshold=a.threshold, include_submitted=not a.no_pool,
                                       kind="power_pool" if a.pp else "regular")
    if cmd == "before-after":
        return W.before_after_performance(a.id, competition=a.competition, team=a.team)
    if cmd == "update-alpha":
        return W.update_alpha(a.id, name=a.name, color=a.color, tags=a.tags, category=a.category,
                              description=a.desc, favorite=a.favorite, hidden=a.hidden, clear=a.clear)
    if cmd == "submit":
        if not a.yes:
            return {"error": "submission is irreversible; re-run with --yes (run `check` first)"}
        return W.submit_alpha(a.id)
    if cmd == "components":
        return W.super_alpha_components(a.id)
    # tags
    if cmd == "tags":
        return W.list_tags()
    if cmd == "tag":
        return W.get_tag(a.id)
    if cmd == "tag-create":
        return W.create_tag(a.name, a.alphas, a.kind)
    if cmd == "tag-update":
        return W.update_tag(a.id, add=a.add, remove=a.remove, rename=a.rename)
    if cmd == "tag-delete":
        return {"deleted": W.delete_tag(a.id)} if a.yes else {"error": "re-run with --yes"}
    if cmd == "tag-corr":
        return W.tag_correlations(a.id, a.kind)
    # account
    simple = {"me": W.me, "pyramids": W.pyramid_overview, "streak": W.streak, "achievements": W.achievements,
              "consultant": W.consultant_summary, "osmosis": W.osmosis_summary, "teams": W.teams,
              "osmosis-alloc": W.osmosis_allocations,
              "status": W.account_status,
              "alpha-counts": W.alphas_count_summary, "categories": W.data_categories, "videos": W.video_courses,
              "forum-topics": lambda: f().topics(), "help-categories": lambda: f().categories()}
    if cmd in simple:
        return simple[cmd]()
    if cmd == "vf":
        return {k: v for k, v in W.value_factor(a.user).items() if k != "raw"}
    if cmd == "sub-days":
        return W.submission_days(a.window)
    if cmd == "submitted":
        return W.recent_submissions(a.days, a.since)
    if cmd == "osmosis-set":
        return W.set_osmosis_points({k: int(v) for k, v in (x.split("=", 1) for x in a.pairs)})
    if cmd == "genius-progress":
        return W.genius_progress(a.level, a.candidates, quarter=a.quarter)
    if cmd == "activity":
        return W.activity(a.name, a.date_from)
    if cmd == "diversity":
        return W.diversity(a.grouping)
    if cmd == "messages":
        return W.messages(a.type, a.limit)
    if cmd == "competitions":
        return W.competitions(mine=a.mine)
    if cmd == "competition":
        return W.competition(a.id)
    if cmd == "board":
        return W.competition_board(a.id, a.board, a.limit, a.offset)
    if cmd == "genius":
        return W.consultant_board(a.board, a.limit, a.offset)
    if cmd == "events":
        return W.events(a.limit, a.upcoming)
    # docs
    if cmd == "docs":
        return W.search_docs(a.search) if a.search else W.docs_index()
    if cmd == "doc":
        return W.get_doc_page(a.page_id)
    if cmd == "docs-dump":
        return W.dump_docs(a.dir)
    if cmd == "examples":
        return W.example_alphas(a.limit)
    # forum
    if cmd == "forum-posts":
        return f().posts(a.topic, a.sort, a.limit, max_chars=None if a.full else 4000)
    if cmd == "forum-post":
        return f().post(a.id, comments=not a.no_comments)
    if cmd == "forum-search":
        return f().search_posts(a.query, a.topic, a.limit)
    if cmd == "forum-crawl":
        return f().crawl_topic(a.topic, a.dir, a.limit, a.since, with_comments=not a.no_comments)
    if cmd == "article-search":
        return f().search_articles(a.query, a.limit)
    if cmd == "article":
        return f().article(a.id)
    if cmd == "articles":
        return f().articles(a.section, a.category, limit=a.limit)
    if cmd == "help-sections":
        return f().sections(a.category)
    # expressions / raw
    if cmd == "scout":
        return W.scout_datasets(a.region, a.delay, a.universe, purpose=a.purpose, exclude=a.exclude, top=a.top)
    if cmd == "rep-fields":
        return W.representative_fields(a.dataset, a.region, a.delay, a.universe, n=a.n, keyword=a.keyword)
    if cmd == "concepts":
        return W.field_concepts(a.dataset, a.region, a.delay, a.universe)
    if cmd == "experiment":
        items = _read_items(a.file)
        st = _settings(a)
        scope = {k: st.pop(k) for k in ("region", "delay", "universe") if k in st}
        rows = W.run_experiment(items, a.tag, mode=_mode(a) or "FULL", concurrency=a.concurrency,
                                pp_budget_check=a.pp_budget, reuse=not a.no_reuse, **scope, **st)
        print(W.results_table(rows), file=sys.stderr)
        return [{k: v for k, v in r.items() if k != "raw"} for r in rows]
    if cmd == "tried":
        return W.find_tried(text=a.text, field=a.field, tag=a.tag, min_sharpe=a.min_sharpe, region=a.region)
    if cmd == "quota":
        return W.simulation_quota()
    if cmd == "robustness":
        return W.compare_robustness(a.ids)
    if cmd == "readiness":
        return W.submission_readiness(a.ids, purpose="regular" if a.regular else "power_pool", quota_left=a.quota)
    if cmd == "pp-presubmit":
        return W.pp_presubmit(a.id, a.idea)
    if cmd == "rules":
        return W.active_rules(a.id)
    if cmd == "desc-check":
        al = W.get_alpha(a.id)
        return W.check_description(a.text or (al.get("regular") or {}).get("description") or "",
                                   (al.get("regular") or {}).get("code"))
    if cmd == "desc-draft":
        return W.draft_pp_description(a.id, a.idea)
    if cmd == "validate":
        return W.validate_expression(a.expression, a.region, a.delay, a.universe, check_fields=not a.no_fields)
    if cmd == "lint":
        fields = None
        if a.dataset:
            fields = [x["id"] for x in W.list_datafields(a.region, a.delay, a.universe, dataset_id=a.dataset, limit=None)]
        return W.check_expression(a.expression, fields=fields)
    if cmd == "expand":
        return W.expand_template(a.template, json.loads(a.values))
    if cmd == "raw":
        return W.raw(a.method, a.path, json.loads(a.params) if a.params else None,
                     json.loads(a.body) if a.body else None, a.poll)
    raise SystemExit(f"unknown command {cmd}")


def main(argv: List[str] | None = None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
        sys.stderr.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except Exception:
        pass
    # allow "--order -is.sharpe" (argparse would read the value as an option)
    src = list(sys.argv[1:] if argv is None else argv)
    args: List[str] = []
    i = 0
    while i < len(src):
        if src[i] in ("--order", "--sort") and i + 1 < len(src) and src[i + 1].startswith("-"):
            args.append(f"{src[i]}={src[i + 1]}")
            i += 2
            continue
        args.append(src[i])
        i += 1
    a = build_parser().parse_args(args)
    for flag, default in (("out", None), ("csv", False), ("compact", False), ("verbose", False)):
        if not hasattr(a, flag):
            setattr(a, flag, default)
    try:
        result = run(a)
    except BrainError as exc:
        print(dump_json({"error": str(exc), "status": exc.status, "detail": exc.payload}), file=sys.stderr)
        return 1
    rows = result.get("alphas") if isinstance(result, dict) and "alphas" in result else result
    if a.out and a.out.lower().endswith(".csv") and isinstance(rows, list):
        to_csv([r if isinstance(r, dict) else {"value": r} for r in rows], a.out)
        print(f"saved {len(rows)} rows -> {a.out}")
    elif a.out:
        dump_json(result, a.out)
        print(f"saved -> {a.out}")
    elif a.csv and isinstance(rows, list):
        print(to_csv([r if isinstance(r, dict) else {"value": r} for r in rows]), end="")
    elif isinstance(result, str):
        print(result)
    else:
        print(dump_json(result, indent=None if a.compact else 2))
    return 0
