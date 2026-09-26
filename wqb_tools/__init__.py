"""wqb_tools - minimal WorldQuant BRAIN toolkit for agents.

    import wqb_tools as wqb
    wqb.whoami()
    wqb.list_datafields("USA", 1, "TOP3000", dataset_id="pv1")
    r = wqb.simulate("rank(-ts_delta(close, 5))", mode="QUICK")
    wqb.check_submission(r["alpha_id"])

Every function accepts an optional `client=` (BrainClient); by default a shared client is used,
authenticating lazily with credentials from env WQB_EMAIL/WQB_PASSWORD, agent_tools/credentials.json,
or ~/.brain_credentials.

Pure standard library (Python >= 3.9): no third-party packages and no files outside this folder are needed.
"""
from __future__ import annotations

from .client import (BASE_URL, BrainAuthError, BrainClient, BrainError, PersonaRequired, get_client,
                     resolve_credentials, set_client)
from .meta import (account_simulation_defaults, list_operators, list_regions, operator_doc, operator_names,
                   permissions, raw_simulation_options, simulation_options, validate_settings)
from .data import (all_datafield_ids, data_categories, dataset_fields_table, get_datafield, get_dataset,
                   list_datafields, list_datasets, request_datafield_visualization, search_datasets)
from .alphas import (alphas_count_summary, before_after_performance, check_submission, create_tag, delete_tag,
                     get_alpha, get_correlations, get_daily_pnl, get_pnl, get_recordset, get_tag, get_yearly_stats,
                     list_alphas, list_recordsets, list_tags, submit_alpha, summarize_alpha, super_alpha_components,
                     tag_correlations, update_alpha, update_tag)
from .simulate import (DEFAULT_SETTINGS, build_payload, cache_lookup, cancel_simulation, get_simulation,
                       normalize_settings, promote_to_full, set_default_settings, simulate, simulate_batch,
                       start_simulation, use_account_defaults, validate_payload, wait_simulation)
from .account import (achievements, activity, agreements, competition, competition_board, competition_levels,
                      competitions, consultant_board, consultant_summary, diversity, events, me, messages,
                      messages_summary, osmosis_summary, pyramid_alphas, pyramid_multipliers, pyramid_overview,
                      simulation_counts, streak, teams, user_profile, whoami)
from .docs import (docs_index, dump_docs, example_alphas, get_doc_page, get_operator_doc, list_tutorials,
                   search_docs, video_courses)
from .forum import CN_CONSULTANT_TOPIC, ForumClient, get_forum
from .expr import analyze_expression, check_expression, expand_template, template_placeholders
from .pp import (GROUPING_FIELDS, classify_alpha, classify_many, field_datasets, operator_count, pp_budget)
from .validate import (field_info, operator_signatures, parse_expression, parse_signature, validate_expression,
                       validate_many)
from .corr import (correlation, correlation_matrix, daily_returns, is_pure_power_pool, plan_submission_order,
                   pnl_series, power_pool_correlation, self_correlation, submitted_pool)
from .runner import (Ledger, default_ledger, find_tried, metrics_row, results_table, run_experiment,
                     simulation_quota)
from .scout import (concept_key, field_concepts, field_families, is_market_wide, is_metadata, representative_fields,
                    scout_datasets)
from .builder import build_combos, screen_fields, signal_correlations, sweep
from .quality import compare_robustness, robustness_report
from .readiness import active_rules, check_description, draft_pp_description, submission_readiness
from .utils import html_to_text, recordset_to_dicts, to_csv

__version__ = "1.3.0"


def login(email: str | None = None, password: str | None = None, force: bool = False):
    """Authenticate (optionally with explicit credentials) and return auth info."""
    c = get_client(email=email, password=password) if (email or password) else get_client()
    return c.authenticate(force=force)


def raw(method: str, path: str, params=None, body=None, poll: bool = False):
    """Call any BRAIN API endpoint directly (escape hatch for endpoints not wrapped here).
    poll=True waits through Retry-After responses (GET only)."""
    c = get_client()
    if poll and method.upper() == "GET":
        r = c.poll(path, params=params)
    else:
        r = c.request(method, path, params=params, json_body=body, raise_on_error=False)
    try:
        data = r.json() if r.content else None
    except ValueError:
        data = r.text
    return {"status": r.status_code, "headers": {k: v for k, v in r.headers.items()
                                                  if k.lower() in ("location", "retry-after") or k.lower().startswith("x-ratelimit")},
            "data": data}
