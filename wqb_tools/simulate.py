"""Simulation (backtest): single / batch / multi-simulation, QUICK vs FULL mode,
Region-Agnostic and SuperAlpha payloads, cancel, local duplicate cache, Quick -> Full promotion."""
from __future__ import annotations

import hashlib
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence

from .alphas import get_alpha, summarize_alpha
from .client import BrainClient, BrainError, get_client
from .utils import append_jsonl, read_jsonl

FINAL_STATUSES = {"COMPLETE", "WARNING", "ERROR", "FAIL", "TIMEOUT", "CANCELLED"}
OK_STATUSES = {"COMPLETE", "WARNING"}
V2 = {"Accept": "application/json;version=2.0"}

DEFAULT_SETTINGS: Dict[str, Any] = {
    "instrumentType": "EQUITY",
    "region": "USA",
    "universe": "TOP3000",
    "delay": 1,
    "decay": 4,
    "neutralization": "SUBINDUSTRY",
    "truncation": 0.08,
    "pasteurization": "ON",
    "unitHandling": "VERIFY",
    "nanHandling": "OFF",
    "maxTrade": "OFF",
    "language": "FASTEXPR",
    "visualization": False,
    "testPeriod": "P1Y",
    "simulationMode": "FULL",
}
SUPER_DEFAULTS = {"selectionHandling": "POSITIVE", "selectionLimit": 10, "componentActivation": "IS"}

_KEY_ALIASES = {
    "instrument_type": "instrumentType", "instrumenttype": "instrumentType",
    "nan_handling": "nanHandling", "nanhandling": "nanHandling",
    "unit_handling": "unitHandling", "unithandling": "unitHandling",
    "max_trade": "maxTrade", "maxtrade": "maxTrade",
    "max_position": "maxPosition", "maxposition": "maxPosition",
    "test_period": "testPeriod", "testperiod": "testPeriod",
    "simulation_mode": "simulationMode", "simulationmode": "simulationMode", "mode": "simulationMode",
    "selection_handling": "selectionHandling", "selectionhandling": "selectionHandling",
    "selection_limit": "selectionLimit", "selectionlimit": "selectionLimit",
    "component_activation": "componentActivation", "componentactivation": "componentActivation",
    "neutralisation": "neutralization", "neut": "neutralization", "lang": "language",
}
_NEUT_ALIASES = {
    "none": "NONE", "ram": "REVERSION_AND_MOMENTUM", "statistical": "STATISTICAL",
    "crowding": "CROWDING", "crowding factors": "CROWDING", "fast": "FAST", "fast factors": "FAST",
    "slow": "SLOW", "slow factors": "SLOW", "market": "MARKET", "sector": "SECTOR", "industry": "INDUSTRY",
    "subindustry": "SUBINDUSTRY", "country": "COUNTRY", "country / region": "COUNTRY",
    "slow_and_fast": "SLOW_AND_FAST", "slow and fast": "SLOW_AND_FAST", "slow + fast factors": "SLOW_AND_FAST",
}
_ON_OFF_KEYS = {"pasteurization", "nanHandling", "maxTrade", "maxPosition"}
_cache_lock = threading.Lock()


# ------------------------------------------------------------------ settings / payload
def set_default_settings(**overrides: Any) -> Dict[str, Any]:
    """Change the process-wide defaults used by build_payload()/simulate()."""
    DEFAULT_SETTINGS.update(normalize_settings(overrides))
    return dict(DEFAULT_SETTINGS)


def use_account_defaults(client: BrainClient | None = None) -> Dict[str, Any]:
    """Load the account's default simulation settings from the platform into DEFAULT_SETTINGS."""
    from .meta import account_simulation_defaults

    acc = account_simulation_defaults(client)
    for k in ("selectionHandling", "selectionLimit", "componentActivation"):
        acc.pop(k, None)
    DEFAULT_SETTINGS.update(acc)
    return dict(DEFAULT_SETTINGS)


def normalize_settings(settings: Dict[str, Any] | None) -> Dict[str, Any]:
    """Accept snake_case keys / friendly values and map them to API names:
    e.g. {'nan_handling': True, 'neutralization': 'ram', 'mode': 'quick'} ->
         {'nanHandling': 'ON', 'neutralization': 'REVERSION_AND_MOMENTUM', 'simulationMode': 'QUICK'}"""
    out: Dict[str, Any] = {}
    for key, value in (settings or {}).items():
        if value is None:
            continue
        k = _KEY_ALIASES.get(key, _KEY_ALIASES.get(key.lower(), key))
        if k == "neutralization" and isinstance(value, str):
            value = _NEUT_ALIASES.get(value.strip().lower(), value.strip().upper())
        elif k in _ON_OFF_KEYS:
            if isinstance(value, bool):
                value = "ON" if value else "OFF"
            else:
                value = str(value).upper()
        elif k in ("simulationMode", "region", "universe", "instrumentType", "language", "unitHandling",
                   "selectionHandling", "componentActivation") and isinstance(value, str):
            value = value.strip().upper()
        elif k in ("delay", "decay", "selectionLimit", "lookback"):
            value = int(value)
        elif k == "truncation":
            value = float(value)
        out[k] = value
    return out


def build_payload(
    expression: str | None = None,
    *,
    alpha_type: str = "REGULAR",
    mode: str | None = None,
    combo: str | None = None,
    selection: str | None = None,
    settings: Dict[str, Any] | None = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """Build a POST /simulations body.
    alpha_type: 'REGULAR' (default) | 'REGION_AGNOSTIC' (region ALL, universe LARGE/MEDIUM/SMALL, delay 1)
                | 'SUPER' (needs combo + selection expressions)
    mode:       'QUICK' (fast, skips correlation/theme/competition checks, not directly submittable) | 'FULL'
    settings / **overrides: any simulation setting (camelCase or snake_case)."""
    alpha_type = alpha_type.upper()
    s = dict(DEFAULT_SETTINGS)
    if alpha_type == "REGION_AGNOSTIC":
        s.update({"region": "ALL", "universe": "LARGE", "delay": 1})
    if alpha_type == "SUPER":
        s.update(SUPER_DEFAULTS)
    s.update(normalize_settings(settings))
    s.update(normalize_settings(overrides))
    if mode:
        s["simulationMode"] = mode.upper()
    payload: Dict[str, Any] = {"type": alpha_type, "settings": s}
    if alpha_type == "SUPER":
        if not (combo and selection):
            raise ValueError("SUPER simulations need both combo and selection expressions")
        payload["combo"], payload["selection"] = _clean_code(combo), _clean_code(selection)
    else:
        if not expression or not str(expression).strip():
            raise ValueError("expression is required")
        payload["regular"] = _clean_code(expression)
    return payload


def _clean_code(code: str) -> str:
    """Drop BOM / zero-width characters that editors and shells sneak in (the API rejects them)."""
    for ch in ("﻿", "​", "‌", "‍", "⁠"):
        code = str(code).replace(ch, "")
    return code.strip()


def validate_payload(payload: Dict[str, Any], client: BrainClient | None = None) -> List[str]:
    """Check settings against OPTIONS /simulations (region/universe/delay/neutralization/choices/ranges)."""
    from .meta import validate_settings

    return validate_settings(payload.get("settings") or {}, client)


# ------------------------------------------------------------------ duplicate cache
def payload_hash(payload: Dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def _cache_path(client: BrainClient):
    return client.cache_dir / "simulation_cache.jsonl"


def cache_lookup(payload: Dict[str, Any], client: BrainClient | None = None) -> str | None:
    """Return alpha_id of an identical, previously simulated payload (official anti-duplicate advice)."""
    c = client or get_client()
    h = payload_hash(payload)
    for row in reversed(read_jsonl(_cache_path(c))):
        if row.get("hash") == h and row.get("alpha_id"):
            return row["alpha_id"]
    return None


def cache_store(payload: Dict[str, Any], alpha_id: str, client: BrainClient | None = None) -> None:
    c = client or get_client()
    with _cache_lock:
        append_jsonl(_cache_path(c), {
            "hash": payload_hash(payload), "alpha_id": alpha_id,
            "date": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "type": payload.get("type"), "expression": payload.get("regular") or payload.get("combo"),
            "mode": (payload.get("settings") or {}).get("simulationMode"),
        })


# ------------------------------------------------------------------ low-level simulation calls
def start_simulation(payload: Dict[str, Any] | List[Dict[str, Any]], client: BrainClient | None = None,
                     max_wait: float = 1800) -> Dict[str, Any]:
    """POST /simulations (single payload or list of 2..10 for multi-simulation).
    Waits/retries while the concurrent-simulation limit is hit. Returns
    {'simulation_id', 'location', 'ratelimit'} or raises BrainError (validation errors are in .payload)."""
    c = client or get_client()
    deadline = time.time() + max_wait
    wait = 5.0
    while True:
        r = c.request("POST", "/simulations", json_body=payload, raise_on_error=False, max_retries=3)
        rl = {k.lower(): v for k, v in r.headers.items() if k.lower().startswith("x-ratelimit")}
        if r.status_code in (200, 201, 202) and r.headers.get("Location"):
            loc = r.headers["Location"]
            return {"simulation_id": loc.rstrip("/").split("/")[-1], "location": loc, "ratelimit": rl}
        body = r.text[:800]
        if r.status_code == 429:
            if rl.get("x-ratelimit-remaining") == "0":
                raise BrainError(f"Daily simulation limit reached (resets in {rl.get('x-ratelimit-reset')}s): {body}", 429)
            if time.time() > deadline:
                raise BrainError(f"Concurrent simulation limit still hit after {max_wait}s: {body}", 429)
            c.log(f"simulation slots busy ({body[:80]}), retry in {wait:.0f}s")
            time.sleep(wait)
            wait = min(wait * 1.5, 30)
            continue
        try:
            detail = r.json()
        except ValueError:
            detail = body
        raise BrainError(f"POST /simulations -> {r.status_code}: {body}", r.status_code, detail)


def get_simulation(simulation_id: str, client: BrainClient | None = None) -> Dict[str, Any]:
    """Single GET /simulations/{id} (no waiting). In progress -> {'progress': 0..1, 'retry_after': s}."""
    c = client or get_client()
    r = c.request("GET", f"/simulations/{simulation_id}", raise_on_error=False)
    data = r.json() if r.content else {}
    if r.status_code >= 400:
        return {"id": simulation_id, "status": "NOT_FOUND" if r.status_code == 404 else "HTTP_ERROR",
                "http_status": r.status_code, "detail": data}
    if r.headers.get("Retry-After"):
        data = {**(data or {}), "id": simulation_id, "status": data.get("status") or "RUNNING",
                "retry_after": float(r.headers["Retry-After"])}
    return data


def wait_simulation(simulation_id: str, timeout: float = 3600, client: BrainClient | None = None,
                    on_progress: Callable[[Any], None] | None = None) -> Dict[str, Any]:
    """Poll GET /simulations/{id} until finished; returns the final simulation JSON."""
    c = client or get_client()
    r = c.poll(f"/simulations/{simulation_id}", timeout=timeout, on_progress=on_progress)
    data = r.json() if r.content else {}
    if r.status_code >= 400:
        return {"id": simulation_id, "status": "HTTP_ERROR", "http_status": r.status_code, "detail": data}
    return data


def cancel_simulation(simulation_id: str, client: BrainClient | None = None) -> bool:
    """DELETE /simulations/{id} - cancel a queued/running simulation."""
    r = (client or get_client()).request("DELETE", f"/simulations/{simulation_id}", headers=V2, raise_on_error=False)
    return r.status_code in (200, 202, 204)


# ------------------------------------------------------------------ results
def _result(payload: Dict[str, Any], sim: Dict[str, Any], client: BrainClient, fetch_alpha: bool,
            extra: Dict[str, Any] | None = None) -> Dict[str, Any]:
    status = str(sim.get("status") or "").upper()
    res: Dict[str, Any] = {
        "ok": status in OK_STATUSES,
        "status": status or "UNKNOWN",
        "simulation_id": sim.get("id"),
        "alpha_id": sim.get("alpha"),
        "type": payload.get("type"),
        "expression": payload.get("regular"),
        "settings": payload.get("settings"),
    }
    if payload.get("type") == "SUPER":
        res["combo"], res["selection"] = payload.get("combo"), payload.get("selection")
    if sim.get("message"):
        res["message"] = sim["message"]
    if sim.get("location"):
        res["error_location"] = sim["location"]
    if sim.get("children"):
        res["children"] = sim["children"]
    if extra:
        res.update(extra)
    if fetch_alpha and res["alpha_id"]:
        _attach_alpha(res, client)
    return res


def _attach_alpha(res: Dict[str, Any], client: BrainClient) -> None:
    try:
        res["alpha"] = summarize_alpha(get_alpha(res["alpha_id"], client))
        if res["alpha"].get("type") == "RA_PARENT":
            # the parent has no stats of its own; per-region results live in the RA children
            from .alphas import super_alpha_components

            res["ra_children"] = [summarize_alpha(a) for a in super_alpha_components(res["alpha_id"], client=client)]
    except Exception as exc:  # noqa: BLE001
        res["alpha_error"] = str(exc)


def _error_result(payload: Dict[str, Any], exc: Exception) -> Dict[str, Any]:
    return {
        "ok": False, "status": "SUBMIT_ERROR", "simulation_id": None, "alpha_id": None,
        "type": payload.get("type"), "expression": payload.get("regular"), "settings": payload.get("settings"),
        "message": str(exc), "detail": getattr(exc, "payload", None),
    }


def _cached_result(payload: Dict[str, Any], alpha_id: str, client: BrainClient, fetch_alpha: bool) -> Dict[str, Any]:
    res = {"ok": True, "status": "CACHED", "cached": True, "simulation_id": None, "alpha_id": alpha_id,
           "type": payload.get("type"), "expression": payload.get("regular"), "settings": payload.get("settings")}
    if fetch_alpha:
        _attach_alpha(res, client)
    return res


# ------------------------------------------------------------------ high level
def simulate(
    expression: str | None = None,
    *,
    payload: Dict[str, Any] | None = None,
    mode: str | None = None,
    alpha_type: str = "REGULAR",
    wait: bool = True,
    fetch_alpha: bool = True,
    use_cache: bool = True,
    validate: bool = False,
    timeout: float = 3600,
    client: BrainClient | None = None,
    **settings: Any,
) -> Dict[str, Any]:
    """Simulate one alpha.
        simulate("rank(-ts_delta(close, 5))", mode="QUICK", region="USA", universe="TOP1000", decay=6)
    Returns {'ok', 'status', 'simulation_id', 'alpha_id', 'expression', 'settings', 'message'?,
             'error_location'?, 'alpha': summarize_alpha(...)?, 'cached'?}
    wait=False returns right after submission with {'simulation_id', 'location', ...}."""
    c = client or get_client()
    if payload is None:
        payload = build_payload(expression, alpha_type=alpha_type, mode=mode, **settings)
    if validate:
        problems = validate_payload(payload, c)
        if problems:
            return {**_error_result(payload, ValueError("; ".join(problems))), "status": "INVALID_SETTINGS"}
    if use_cache:
        hit = cache_lookup(payload, c)
        if hit:
            return _cached_result(payload, hit, c, fetch_alpha)
    try:
        started = start_simulation(payload, c)
    except BrainError as exc:
        return _error_result(payload, exc)
    if not wait:
        return {"ok": True, "status": "SUBMITTED", **started, "expression": payload.get("regular"),
                "settings": payload.get("settings")}
    sim = wait_simulation(started["simulation_id"], timeout, c)
    res = _result(payload, sim, c, fetch_alpha, {"ratelimit": started.get("ratelimit")})
    if res["ok"] and res.get("alpha_id"):
        cache_store(payload, res["alpha_id"], c)
    return res


def _group_key(p: Dict[str, Any]) -> tuple:
    s = p.get("settings") or {}
    return (p.get("type"), s.get("instrumentType"), s.get("region"), s.get("delay"), s.get("language"))


def simulate_batch(
    items: Sequence[Any],
    *,
    mode: str | None = None,
    concurrency: int = 3,
    multi: bool | None = None,
    multi_size: int = 10,
    fetch_alpha: bool = True,
    use_cache: bool = True,
    timeout: float = 7200,
    on_result: Callable[[int, Dict[str, Any]], None] | None = None,
    out_jsonl: str | None = None,
    client: BrainClient | None = None,
    **common_settings: Any,
) -> List[Dict[str, Any]]:
    """Simulate many alphas, returning results in input order.
    items: expressions (str), or dicts {'expression': ..., 'settings': {...}, 'alpha_type': ..., 'mode': ...},
           or ready payloads (dicts containing 'type' and 'settings').
    multi: use multi-simulation (2..10 alphas per request; needs MULTI_SIMULATION permission; items are grouped
           by type/instrument/region/delay/language). Default: auto (on if permitted).
    concurrency: simultaneous simulation requests (each multi-sim counts as one; consultants may use up to 8).
    on_result(index, result) is called as each finishes; out_jsonl appends each result to a file."""
    c = client or get_client()
    payloads: List[Dict[str, Any]] = []
    for it in items:
        if isinstance(it, str):
            payloads.append(build_payload(it, mode=mode, **common_settings))
        elif isinstance(it, dict) and "type" in it and "settings" in it:
            payloads.append(it)
        elif isinstance(it, dict):
            st = {**common_settings, **(it.get("settings") or {})}
            payloads.append(build_payload(
                it.get("expression") or it.get("regular"), alpha_type=it.get("alpha_type", "REGULAR"),
                mode=it.get("mode") or mode, combo=it.get("combo"), selection=it.get("selection"), **st))
        else:
            raise TypeError(f"unsupported batch item: {it!r}")

    results: List[Dict[str, Any] | None] = [None] * len(payloads)
    lock = threading.Lock()

    def emit(i: int, res: Dict[str, Any]) -> None:
        res["index"] = i
        with lock:
            results[i] = res
            if out_jsonl:
                append_jsonl(out_jsonl, res)
        if on_result:
            try:
                on_result(i, res)
            except Exception:  # noqa: BLE001
                pass

    # dedupe: cache hits and identical payloads inside the batch
    pending: Dict[str, List[int]] = {}
    for i, p in enumerate(payloads):
        hit = cache_lookup(p, c) if use_cache else None
        if hit:
            emit(i, _cached_result(p, hit, c, fetch_alpha))
            continue
        pending.setdefault(payload_hash(p), []).append(i)
    unique = [idx[0] for idx in pending.values()]

    if multi is None:
        multi = "MULTI_SIMULATION" in c.permissions
    jobs: List[List[int]] = []
    if multi:
        groups: Dict[tuple, List[int]] = {}
        for i in unique:
            groups.setdefault(_group_key(payloads[i]), []).append(i)
        for idxs in groups.values():
            size = max(2, min(10, multi_size))
            jobs.extend(idxs[k:k + size] for k in range(0, len(idxs), size))
    else:
        jobs = [[i] for i in unique]

    def finish(i: int, res: Dict[str, Any]) -> None:
        if res.get("ok") and res.get("alpha_id"):
            cache_store(payloads[i], res["alpha_id"], c)
        for j in pending[payload_hash(payloads[i])]:
            emit(j, dict(res) if j == i else {**res, "duplicate_of": i})

    def run_single(i: int) -> None:
        try:
            started = start_simulation(payloads[i], c)
            sim = wait_simulation(started["simulation_id"], timeout, c)
            finish(i, _result(payloads[i], sim, c, fetch_alpha))
        except Exception as exc:  # noqa: BLE001
            finish(i, _error_result(payloads[i], exc))

    def run_multi(idxs: List[int]) -> None:
        if len(idxs) == 1:
            return run_single(idxs[0])
        try:
            started = start_simulation([payloads[i] for i in idxs], c)
            parent = wait_simulation(started["simulation_id"], timeout, c)
        except Exception as exc:  # noqa: BLE001
            parent = {"status": "SUBMIT_ERROR", "message": str(exc)}
        children = parent.get("children") or []
        if not children:
            # whole multi-sim rejected (often one bad member) -> fall back to single simulations
            c.log(f"multi-simulation failed ({parent.get('status')}: {parent.get('message')}); retrying singly")
            for i in idxs:
                run_single(i)
            return
        for i, child_id in zip(idxs, children):
            try:
                sim = wait_simulation(child_id, timeout, c)
                finish(i, _result(payloads[i], sim, c, fetch_alpha, {"parent_simulation_id": parent.get("id") or started["simulation_id"]}))
            except Exception as exc:  # noqa: BLE001
                finish(i, _error_result(payloads[i], exc))
        for i in idxs[len(children):]:
            finish(i, {**_error_result(payloads[i], BrainError("missing child simulation")), "status": "ERROR"})

    with ThreadPoolExecutor(max_workers=max(1, concurrency)) as pool:
        futures = [pool.submit(run_multi, job) for job in jobs]
        for f in as_completed(futures):
            f.result()
    return [r for r in results if r is not None]


def promote_to_full(alpha_id: str, *, wait: bool = True, fetch_alpha: bool = True,
                    client: BrainClient | None = None, **overrides: Any) -> Dict[str, Any]:
    """Re-simulate an existing (e.g. QUICK-mode) alpha in FULL mode so it gets the complete checks
    and becomes submittable. Extra keyword args override settings."""
    c = client or get_client()
    alpha = get_alpha(alpha_id, c)
    settings = {k: v for k, v in (alpha.get("settings") or {}).items() if k not in ("startDate", "endDate")}
    settings.update(normalize_settings(overrides))
    settings["simulationMode"] = "FULL"
    atype = alpha.get("type") or "REGULAR"
    if atype == "SUPER":
        payload = {"type": "SUPER", "settings": settings,
                   "combo": (alpha.get("combo") or {}).get("code"), "selection": (alpha.get("selection") or {}).get("code")}
    else:
        code = alpha.get("regular")
        # RA parent -> re-run region-agnostic; RA child / regular -> re-run as a regular alpha in its own region
        payload = {"type": "REGION_AGNOSTIC" if atype == "RA_PARENT" else "REGULAR", "settings": settings,
                   "regular": code.get("code") if isinstance(code, dict) else code}
    res = simulate(payload=payload, wait=wait, fetch_alpha=fetch_alpha, use_cache=False, client=c)
    res["source_alpha_id"] = alpha_id
    return res
