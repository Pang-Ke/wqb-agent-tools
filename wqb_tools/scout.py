"""(4) dataset scouting: rank datasets for a scope, collapse duplicate field families, flag market-wide fields,
pick representative fields ready for screening."""
from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Optional

from .client import BrainClient, get_client

# descriptions that usually mean "same value for every stock" (useless cross-sectionally)
_MARKET_WIDE = re.compile(
    r"\b(commodit\w*|crude oil|natural gas|gold|silver|copper|corn|soybean|wheat|index value|stock price index|"
    r"market return|market expected return|interest rate|yield curve|treasury|cpi\b|consumer price index|"
    r"unemployment rate|exchange rate|fx rate|gdp|inflation rate|holiday|trading hours)", re.I)
_STOCK_SPECIFIC = re.compile(r"\b(stock'?s?|company|firm|issuer|per share|sensitivity|beta|residual|exposure|"
                             r"correlation between)", re.I)


_CALENDAR = re.compile(r"\b(week number|month code|quarter code|market regime|regime label|trading days (remaining )?"
                       r"(until|to) the end of the (current )?month|day of (the )?week)", re.I)
# name tokens that indicate metadata (dates, ids, timestamps, share counts, period types)
_JUNK_TOKENS = {"date", "time", "timestamp", "period", "type", "id", "ticker", "isin", "cusip", "sedol", "ric", "code",
                "shares", "call", "received", "receivetime", "wqreceivetime", "week", "month", "regime", "epoch", "year"}
_JUNK_SUBSTR = ("periodend", "yearend", "periodtype", "sharesoutstanding", "receivetime", "fiscalyear")
_PREFER = re.compile(r"\b(prob\w*|predict\w*|forecast\w*|score|signal|sentiment|ratio|margin|yield|return on|growth|"
                     r"percent\w*|rank|surprise|revision\w*|confidence|expected return|estimate)", re.I)
_RAW_AMOUNT = re.compile(r"^(quarterly |annual |total )?(revenue|net income|earnings before|ebit\w*|sales|assets|"
                         r"liabilities|cash|debt|capital expenditure|operating income|gross profit)\b", re.I)


_NON_SIGNAL_DATASET = re.compile(r"holiday|trading hours|calendar|universe dataset", re.I)


def is_market_wide(description: str) -> bool:
    d = description or ""
    return bool(_CALENDAR.search(d)) or (bool(_MARKET_WIDE.search(d)) and not _STOCK_SPECIFIC.search(d))


def is_metadata(field_id: str) -> bool:
    toks = set(re.split(r"[_\d]+", field_id.lower()))
    return bool(toks & _JUNK_TOKENS) or any(s in field_id.lower() for s in _JUNK_SUBSTR)


def field_priority(f: Dict[str, Any]) -> float:
    """Heuristic usefulness score: coverage + predictive-sounding description - raw size amounts."""
    d = f.get("description") or ""
    return ((f.get("coverage") or 0) + (0.5 if _PREFER.search(d) else 0.0)
            - (0.7 if _RAW_AMOUNT.search(d) and "per share" not in d.lower() else 0.0))


def scout_datasets(region: str = "USA", delay: int = 1, universe: str = "TOP3000", *, purpose: str = "power_pool",
                   exclude: Iterable[str] = (), min_coverage: float = 0.5, top: int = 40,
                   client: BrainClient | None = None) -> List[Dict[str, Any]]:
    """Rank datasets. purpose='power_pool' ignores platform crowding (prod correlation is waived for pure PP);
    purpose='regular' penalises crowded datasets (prod correlation < 0.7 needed).
    score = 1.0*valueScore + 3*coverage + 1*dateCoverage + 1.5*pyramidMultiplier - crowding_penalty - size_penalty."""
    from .account import pyramid_overview
    from .data import list_datasets

    c = client or get_client()
    mult = {}
    try:
        for p in pyramid_overview(c):
            if p["region"] == region and p["delay"] == delay:
                mult[p["category"]] = (p.get("multiplier"), p.get("alphaCount"))
    except Exception:  # noqa: BLE001
        pass
    rows = []
    for d in list_datasets(region, delay, universe, limit=None, client=c):
        if d["id"] in set(exclude) or (d.get("coverage") or 0) < min_coverage:
            continue
        if _NON_SIGNAL_DATASET.search(d.get("name") or ""):   # calendars / universe membership: same for every stock
            continue
        cat = (d.get("category") or {}).get("id")
        pm, mine = mult.get(cat, (None, None))
        pm = d.get("pyramidMultiplier") or pm or 1.0
        crowd = (d.get("alphaCount") or 0) / 1000.0
        score = ((d.get("valueScore") or 0) + 3 * (d.get("coverage") or 0) + (d.get("dateCoverage") or 0) + 1.5 * pm
                 - (min(3.0, crowd) if purpose == "regular" else 0.0)
                 - (0.5 if (d.get("fieldCount") or 0) > 800 else 0.0))
        rows.append({"id": d["id"], "name": d.get("name"), "category": cat, "fields": d.get("fieldCount"),
                     "coverage": d.get("coverage"), "dateCoverage": d.get("dateCoverage"), "valueScore": d.get("valueScore"),
                     "alphaCount": d.get("alphaCount"), "userCount": d.get("userCount"), "pyramidMultiplier": pm,
                     "myPyramidAlphas": mine, "score": round(score, 3)})
    return sorted(rows, key=lambda r: -r["score"])[:top]


def field_families(dataset_id: str, region: str = "USA", delay: int = 1, universe: str = "TOP3000",
                   client: BrainClient | None = None) -> List[Dict[str, Any]]:
    """Group near-duplicate fields (version suffixes like _3/_31, star_sr_x vs x_main) and keep one representative
    (highest coverage, then most used). Each family: {family, representative, type, coverage, members, market_wide}."""
    from .data import list_datafields

    fields = list_datafields(region, delay, universe, dataset_id=dataset_id, limit=None, client=client)
    fam: Dict[str, List[Dict[str, Any]]] = {}
    for f in fields:
        key = re.sub(r"(_\d+)+$", "", f["id"])
        key = re.sub(r"_main$", "", key)
        fam.setdefault(key, []).append(f)
    out = []
    for k, members in fam.items():
        rep = max(members, key=lambda f: ((f.get("coverage") or 0), (f.get("alphaCount") or 0)))
        row = {"family": k, "representative": rep["id"], "type": rep.get("type"), "coverage": rep.get("coverage"),
               "dateCoverage": rep.get("dateCoverage"), "alphaCount": sum(m.get("alphaCount") or 0 for m in members),
               "description": rep.get("description"), "members": [m["id"] for m in members],
               "market_wide": is_market_wide(rep.get("description") or ""), "metadata": is_metadata(rep["id"])}
        row["priority"] = round(field_priority(row), 3)
        out.append(row)
    return sorted(out, key=lambda r: -r["priority"])


def representative_fields(dataset_id: str, region: str = "USA", delay: int = 1, universe: str = "TOP3000", *,
                          n: int = 16, min_coverage: float = 0.6, types: Iterable[str] = ("MATRIX", "VECTOR"),
                          include: Iterable[str] = (), keyword: str | None = None, per_stem: int = 2,
                          client: BrainClient | None = None) -> List[Dict[str, Any]]:
    """Up to n screening-ready fields: one per family, highest priority first; drops market-wide / calendar and
    metadata fields (dates, ids, timestamps, share counts), low coverage and disallowed types; at most `per_stem`
    fields whose ids differ only by digits (e.g. img120d_q2_* vs img120d_q5_*). keyword: regex filter on id+description.
    Each has 'term' = the field expression to plug into templates (vector fields wrapped in vec_avg)."""
    fams = field_families(dataset_id, region, delay, universe, client)
    keep = [f for f in fams if f["representative"] in set(include)]
    stems: Dict[str, int] = {}
    kw = re.compile(keyword, re.I) if keyword else None
    for f in fams:
        if len(keep) >= n:
            break
        if f in keep or f["market_wide"] or f["metadata"] or (f["coverage"] or 0) < min_coverage \
                or str(f["type"]).upper() not in set(types):
            continue
        if kw and not kw.search(f"{f['representative']} {f['description']}"):
            continue
        stem = re.sub(r"\d+", "#", f["representative"])
        if stems.get(stem, 0) >= per_stem:
            continue
        stems[stem] = stems.get(stem, 0) + 1
        keep.append(f)
    for f in keep:
        f["term"] = f"vec_avg({f['representative']})" if str(f["type"]).upper() == "VECTOR" else f["representative"]
    return keep
