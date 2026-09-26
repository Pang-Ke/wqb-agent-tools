"""Alphas: details, listing/filtering, record sets, submission checks, correlations,
performance comparison, properties, submission, SuperAlpha components, alpha lists (tags)."""
from __future__ import annotations

import re
import time
from typing import Any, Dict, Iterable, List, Optional
from urllib.parse import quote

from .client import BrainClient, BrainError, get_client
from .utils import recordset_columns, recordset_to_dicts

V2 = {"Accept": "application/json;version=2.0"}
METRIC_KEYS = ("sharpe", "fitness", "turnover", "returns", "drawdown", "margin", "pnl", "longCount", "shortCount")
SETTING_KEYS = (
    "region", "universe", "delay", "decay", "neutralization", "truncation", "pasteurization",
    "nanHandling", "unitHandling", "maxTrade", "maxPosition", "testPeriod", "simulationMode", "language",
    "lookback", "selectionHandling", "selectionLimit",
)


# ------------------------------------------------------------------ details
def get_alpha(alpha_id: str, client: BrainClient | None = None) -> Dict[str, Any]:
    """GET /alphas/{id} - raw alpha JSON (settings, regular/combo/selection code, is/os/train/test stats, checks...)."""
    c = client or get_client()
    r = c.poll(f"/alphas/{alpha_id}", timeout=300)
    if r.status_code >= 400:
        raise BrainError(f"GET /alphas/{alpha_id} -> {r.status_code}: {r.text[:300]}", r.status_code)
    return r.json()


def _metrics(block: Any) -> Dict[str, Any] | None:
    if not isinstance(block, dict):
        return None
    return {k: block.get(k) for k in METRIC_KEYS if k in block}


def summarize_alpha(alpha: Dict[str, Any]) -> Dict[str, Any]:
    """Compact, agent-friendly view of an alpha JSON."""
    code = alpha.get("regular")
    if isinstance(code, dict):
        expression = code.get("code")
        description = code.get("description")
    else:
        expression, description = code, None
    is_block = alpha.get("is") or {}
    checks: Dict[str, List[Any]] = {}
    for chk in is_block.get("checks") or []:
        item = {k: chk.get(k) for k in ("name", "value", "limit") if chk.get(k) is not None}
        checks.setdefault(str(chk.get("result", "UNKNOWN")), []).append(item if len(item) > 1 else chk.get("name"))
    settings = alpha.get("settings") or {}
    out: Dict[str, Any] = {
        "id": alpha.get("id"),
        "type": alpha.get("type"),
        "status": alpha.get("status"),
        "stage": alpha.get("stage"),
        "grade": alpha.get("grade"),
        "name": alpha.get("name"),
        "dateCreated": alpha.get("dateCreated"),
        "dateSubmitted": alpha.get("dateSubmitted"),
        "expression": expression,
        "settings": {k: settings[k] for k in SETTING_KEYS if k in settings},
        "is": _metrics(is_block),
        "checks": checks,
        "passedChecks": bool(is_block.get("checks")) and not checks.get("FAIL"),
    }
    if description:
        out["description"] = description
    if isinstance(alpha.get("combo"), dict):
        out["combo"] = alpha["combo"].get("code")
    if isinstance(alpha.get("selection"), dict):
        out["selection"] = alpha["selection"].get("code")
    for extra in ("riskNeutralized", "investabilityConstrained"):
        if isinstance(is_block.get(extra), dict):
            out[extra] = _metrics(is_block[extra])
    for block in ("train", "test", "os", "prod"):
        if isinstance(alpha.get(block), dict):
            out[block] = _metrics(alpha[block])
    for key in ("children", "tags", "classifications", "pyramids", "themes", "competitions", "color", "category",
                "favorite", "hidden"):
        if alpha.get(key):
            out[key] = alpha[key]
    return out


# ------------------------------------------------------------------ listing
_FILTER_RE = re.compile(r"^([\w.\-]+)\s*(>=|<=|!=|>|<|=|~)\s*(.*)$")


def _encode_filter(f: str) -> str:
    """'is.sharpe>=1.5' -> 'is.sharpe%3E=1.5'; 'status=UNSUBMITTED|IS_FAIL' -> 'status=UNSUBMITTED%1FIS_FAIL'."""
    m = _FILTER_RE.match(f.strip())
    if not m:
        raise ValueError(f"Bad filter {f!r}. Use e.g. 'is.sharpe>=1.5', 'settings.region=USA', 'dateCreated>=2026-01-01T00:00:00-05:00'")
    field, op, value = m.groups()
    value = value.replace("|", "\x1f")
    return quote(field + op, safe="=.-_") + quote(value, safe=".-_:,")


def list_alphas(
    filters: Iterable[str] | None = None,
    *,
    status: str | None = None,
    stage: str | None = None,
    region: str | None = None,
    delay: int | None = None,
    universe: str | None = None,
    alpha_type: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    sharpe_min: float | None = None,
    fitness_min: float | None = None,
    hidden: bool | None = None,
    favorite: bool | None = None,
    order: str = "-dateCreated",
    limit: int | None = 50,
    offset: int = 0,
    summary: bool = True,
    user: str = "self",
    client: BrainClient | None = None,
) -> Dict[str, Any]:
    """GET /users/self/alphas with filters.
    filters: raw filter expressions, e.g. ['is.sharpe>=1.5', 'is.turnover<0.3', 'settings.neutralization=MARKET',
             'dateCreated>=2026-09-01T00:00:00-04:00', 'status=UNSUBMITTED|IS_FAIL']
    status:  UNSUBMITTED | ACTIVE | DECOMMISSIONED | IS_FAIL ...   stage: IS | OS | PROD
    order:   '-dateCreated', '-is.sharpe', '-is.fitness', 'is.turnover', '-dateSubmitted' ...
    limit=None -> fetch all matching.
    Returns {'count': total, 'alphas': [...summaries or raw...]}."""
    c = client or get_client()
    fs = list(filters or [])
    for key, val in (
        ("status", status), ("stage", stage), ("settings.region", region), ("settings.delay", delay),
        ("settings.universe", universe), ("type", alpha_type),
    ):
        if val is not None:
            fs.append(f"{key}={val}")
    if date_from:
        fs.append(f"dateCreated>={date_from}")
    if date_to:
        fs.append(f"dateCreated<{date_to}")
    if sharpe_min is not None:
        fs.append(f"is.sharpe>={sharpe_min}")
    if fitness_min is not None:
        fs.append(f"is.fitness>={fitness_min}")
    if hidden is not None:
        fs.append(f"hidden={str(hidden).lower()}")
    if favorite is not None:
        fs.append(f"favorite={str(favorite).lower()}")
    if order:
        fs.append(f"order={order}")
    base = "&".join(_encode_filter(f) for f in fs)
    out: List[Dict[str, Any]] = []
    total = None
    while True:
        size = 100 if limit is None else max(1, min(100, limit - len(out)))
        data = c.get(f"/users/{user}/alphas?{base}&limit={size}&offset={offset}")
        items = data.get("results", [])
        total = data.get("count", total)
        out.extend(items)
        offset += len(items)
        if not items or (limit is not None and len(out) >= limit) or (total is not None and offset >= total):
            break
    return {"count": total, "alphas": [summarize_alpha(a) for a in out] if summary else out}


def alphas_count_summary(client: BrainClient | None = None) -> Dict[str, Any]:
    """GET /users/self/alphas/summary -> {'is': n, 'os': n, 'prod': n}."""
    return (client or get_client()).get("/users/self/alphas/summary")


# ------------------------------------------------------------------ record sets
def list_recordsets(alpha_id: str, client: BrainClient | None = None) -> List[Dict[str, Any]]:
    """GET /alphas/{id}/recordsets -> [{'name','title'}] (pnl, sharpe, turnover, daily-pnl, yearly-stats, ...)."""
    c = client or get_client()
    r = c.poll(f"/alphas/{alpha_id}/recordsets", timeout=300)
    return (r.json() or {}).get("results", []) if r.status_code == 200 else []


def get_recordset(alpha_id: str, name: str, client: BrainClient | None = None, raw: bool = False) -> Any:
    """GET /alphas/{id}/recordsets/{name}; waits while the platform prepares it.
    Returns {'name', 'columns', 'rows': [dict, ...]} (or the raw payload if raw=True)."""
    c = client or get_client()
    r = c.poll(f"/alphas/{alpha_id}/recordsets/{name}", timeout=600)
    if r.status_code >= 400:
        raise BrainError(f"recordset {name} for {alpha_id} -> {r.status_code}: {r.text[:300]}", r.status_code)
    payload = r.json()
    if raw:
        return payload
    return {"name": name, "columns": recordset_columns(payload), "rows": recordset_to_dicts(payload)}


def get_pnl(alpha_id: str, client: BrainClient | None = None) -> List[Dict[str, Any]]:
    """Cumulative PnL rows: date, pnl, (risk-neutralized-pnl, investability-constrained-pnl)."""
    return get_recordset(alpha_id, "pnl", client)["rows"]


def get_daily_pnl(alpha_id: str, client: BrainClient | None = None) -> List[Dict[str, Any]]:
    return get_recordset(alpha_id, "daily-pnl", client)["rows"]


def get_yearly_stats(alpha_id: str, client: BrainClient | None = None) -> List[Dict[str, Any]]:
    """Per-year pnl, bookSize, long/shortCount, turnover, sharpe, returns, drawdown, margin, fitness, stage."""
    return get_recordset(alpha_id, "yearly-stats", client)["rows"]


# ------------------------------------------------------------------ checks & correlations
def check_submission(alpha_id: str, timeout: float = 900, client: BrainClient | None = None) -> Dict[str, Any]:
    """GET /alphas/{id}/check - runs the full pre-submission test suite (self/prod correlation,
    sub-universe, pyramid/theme/competition matches...). Polls until ready.
    Returns {'alpha_id', 'canSubmit', 'fail': [...], 'warning': [...], 'pending': [...], 'pass': [...], 'checks': [...]}
    (plus 'error' when the platform refuses, e.g. QUICK-mode alphas)."""
    c = client or get_client()
    r = c.poll(f"/alphas/{alpha_id}/check", timeout=timeout, headers=V2)
    if r.status_code >= 400:
        # e.g. 400 "Cannot check submission for QUICK mode alphas" -> use promote_to_full() first
        try:
            detail = r.json()
        except ValueError:
            detail = r.text[:300]
        return {"alpha_id": alpha_id, "canSubmit": False, "error": detail, "http_status": r.status_code,
                "fail": [], "error_checks": [], "pending": [], "warning": [], "pass": [], "checks": []}
    data = r.json() or {}
    checks = (data.get("is") or {}).get("checks") or data.get("checks") or []
    groups: Dict[str, List[Dict[str, Any]]] = {"FAIL": [], "WARNING": [], "PENDING": [], "PASS": [], "ERROR": []}
    for chk in checks:
        groups.setdefault(str(chk.get("result")), []).append(chk)
    return {
        "alpha_id": alpha_id,
        "canSubmit": bool(checks) and not groups["FAIL"] and not groups["ERROR"] and not groups["PENDING"],
        "fail": groups["FAIL"],
        "error_checks": groups["ERROR"],
        "pending": groups["PENDING"],
        "warning": groups["WARNING"],
        "pass": [chk.get("name") for chk in groups["PASS"]],
        "checks": checks,
    }


def get_correlations(alpha_id: str, kind: str = "self", timeout: float = 600, client: BrainClient | None = None) -> Dict[str, Any]:
    """GET /alphas/{id}/correlations/{self|prod|power-pool}.
    self:       most-correlated of your own submitted alphas (rows: id, name, region, universe, correlation, sharpe, ...)
    prod:       histogram of correlation vs. all production alphas (rows: min, max, alphas)
    power-pool: correlation vs. your Power Pool alphas (the POWER_POOL_CORRELATION test, limit 0.5)
    Returns {'kind', 'max', 'min', 'rows': [...]}"""
    if kind not in ("self", "prod", "power-pool"):
        raise ValueError("kind must be 'self', 'prod' or 'power-pool'")
    c = client or get_client()
    r = c.poll(f"/alphas/{alpha_id}/correlations/{kind}", timeout=timeout, headers=V2)
    if r.status_code >= 400:
        raise BrainError(f"correlations/{kind} {alpha_id} -> {r.status_code}: {r.text[:300]}", r.status_code)
    data = r.json() or {}
    return {"kind": kind, "max": data.get("max"), "min": data.get("min"), "rows": recordset_to_dicts(data)}


def before_after_performance(
    alpha_id: str,
    competition: str | None = None,
    team: str | None = None,
    timeout: float = 600,
    client: BrainClient | None = None,
) -> Dict[str, Any]:
    """How adding this (unsubmitted) alpha changes your portfolio / competition score.
    competition -> /competitions/{c}/alphas/{id}/before-and-after-performance
    team        -> /teams/{t}/alphas/{id}/before-and-after-performance
    default     -> /users/self/alphas/{id}/before-and-after-performance
    Returns raw payload: {'partitionName', 'stats': {'before','after'}, 'yearlyStats': {...}, 'score': ...}"""
    c = client or get_client()
    mode = (get_alpha(alpha_id, c).get("settings") or {}).get("simulationMode")
    if mode == "QUICK":
        # the platform never finishes this computation for QUICK alphas (endless Retry-After)
        raise BrainError(f"{alpha_id} is a QUICK-mode alpha; run promote_to_full() first", 400)
    if competition:
        path = f"/competitions/{competition}/alphas/{alpha_id}/before-and-after-performance"
    elif team:
        path = f"/teams/{team}/alphas/{alpha_id}/before-and-after-performance"
    else:
        path = f"/users/self/alphas/{alpha_id}/before-and-after-performance"
    r = c.poll(path, timeout=timeout)
    data = r.json() if r.content else {}
    if r.status_code >= 400:
        raise BrainError(f"before-and-after {alpha_id} -> {r.status_code}: {r.text[:300]}", r.status_code, data)
    return data


# ------------------------------------------------------------------ properties / submission
def update_alpha(
    alpha_id: str,
    *,
    name: str | None = None,
    color: str | None = None,
    tags: List[str] | None = None,
    category: str | None = None,
    description: str | None = None,
    combo_description: str | None = None,
    selection_description: str | None = None,
    favorite: bool | None = None,
    hidden: bool | None = None,
    clear: Iterable[str] = (),
    client: BrainClient | None = None,
) -> Dict[str, Any]:
    """PATCH /alphas/{id}. Only provided fields are sent; pass names in `clear` (e.g. ['name','color'])
    to reset them to null. color: RED|YELLOW|GREEN|BLUE|PURPLE. description = regular.description
    (Power Pool alphas need a description >= 100 chars)."""
    body: Dict[str, Any] = {}
    for key, val in (("name", name), ("color", color), ("tags", tags), ("category", category),
                     ("favorite", favorite), ("hidden", hidden)):
        if val is not None:
            body[key] = val
    if description is not None:
        body["regular"] = {"description": description}
    if combo_description is not None:
        body["combo"] = {"description": combo_description}
    if selection_description is not None:
        body["selection"] = {"description": selection_description}
    for key in clear:
        body[key] = None
    if not body:
        raise ValueError("nothing to update")
    return (client or get_client()).patch(f"/alphas/{alpha_id}", body)


def submit_alpha(alpha_id: str, timeout: float = 1200, client: BrainClient | None = None) -> Dict[str, Any]:
    """POST /alphas/{id}/submit then poll GET /alphas/{id}/submit until done.
    IRREVERSIBLE: the alpha enters OS. Run check_submission() first.
    Returns {'alpha_id', 'submitted': bool, 'status', 'http_status', 'response'}."""
    c = client or get_client()
    r = c.request("POST", f"/alphas/{alpha_id}/submit", headers=V2, raise_on_error=False)
    if r.status_code < 400 and r.headers.get("Retry-After"):
        r = c.poll(f"/alphas/{alpha_id}/submit", timeout=timeout, headers=V2)
    try:
        body = r.json() if r.content else {}
    except ValueError:
        body = r.text
    alpha = get_alpha(alpha_id, c)
    submitted = alpha.get("status") not in (None, "UNSUBMITTED") or bool(alpha.get("dateSubmitted"))
    return {
        "alpha_id": alpha_id,
        "submitted": submitted,
        "status": alpha.get("status"),
        "stage": alpha.get("stage"),
        "http_status": r.status_code,
        "response": body,
    }


def super_alpha_components(alpha_id: str, limit: int | None = None, client: BrainClient | None = None) -> List[Dict[str, Any]]:
    """GET /alphas/{id}/alphas - component alphas of a SuperAlpha, or the per-region RA_CHILD alphas
    of a Region-Agnostic parent (RA_PARENT)."""
    return (client or get_client()).paginate(f"/alphas/{alpha_id}/alphas", limit=limit, page_size=50)


# ------------------------------------------------------------------ alpha lists / tags
def list_tags(client: BrainClient | None = None) -> List[Dict[str, Any]]:
    """GET /users/self/tags - your alpha lists / tags."""
    return (client or get_client()).paginate("/users/self/tags", limit=None, page_size=50)


def get_tag(tag_id: str, client: BrainClient | None = None) -> Dict[str, Any]:
    return (client or get_client()).get(f"/tags/{tag_id}")


def create_tag(name: str, alphas: List[str] | None = None, tag_type: str = "LIST", client: BrainClient | None = None) -> Dict[str, Any]:
    """POST /tags {type: LIST|TAG|CATEGORY|COLOR, name, alphas}."""
    return (client or get_client()).post("/tags", {"type": tag_type, "name": name, "alphas": alphas or []})


def update_tag(
    tag_id: str,
    *,
    add: List[str] | None = None,
    remove: List[str] | None = None,
    rename: str | None = None,
    client: BrainClient | None = None,
) -> List[Any]:
    """PATCH /tags/{id}: add/remove alphas or rename."""
    c = client or get_client()
    results = []
    if rename:
        results.append(c.patch(f"/tags/{tag_id}", {"name": rename}))
    if add:
        results.append(c.patch(f"/tags/{tag_id}", {"op": "add", "alphas": add}))
    if remove:
        results.append(c.patch(f"/tags/{tag_id}", {"op": "remove", "alphas": remove}))
    return results


def delete_tag(tag_id: str, client: BrainClient | None = None) -> bool:
    r = (client or get_client()).request("DELETE", f"/tags/{tag_id}", raise_on_error=False)
    return r.status_code in (200, 204)


def tag_correlations(tag_id: str, kind: str = "inner", timeout: float = 600, client: BrainClient | None = None) -> Dict[str, Any]:
    """GET /tags/{id}/correlations/{inner|self} - correlation among alphas in a list / vs. your submitted alphas."""
    c = client or get_client()
    r = c.poll(f"/tags/{tag_id}/correlations/{kind}", timeout=timeout)
    data = r.json() if r.content else {}
    if r.status_code >= 400:
        raise BrainError(f"tag correlations -> {r.status_code}: {r.text[:300]}", r.status_code, data)
    return {"kind": kind, "max": data.get("max"), "min": data.get("min"), "rows": recordset_to_dicts(data), "raw": data}
