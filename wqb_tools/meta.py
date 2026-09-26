"""Platform metadata: simulation setting options, regions/universes, operators, account defaults."""
from __future__ import annotations

import json
import time
from typing import Any, Dict, List, Optional

from .client import BrainClient, get_client

_OPTIONS_CACHE: Dict[str, Any] = {}


def _values(choices: Any) -> List[Any]:
    return [c.get("value") for c in choices or [] if isinstance(c, dict)]


def raw_simulation_options(client: BrainClient | None = None) -> Dict[str, Any]:
    """OPTIONS /simulations - full schema of the simulation payload."""
    c = client or get_client()
    if "raw" not in _OPTIONS_CACHE:
        _OPTIONS_CACHE["raw"] = c.options("/simulations")
    return _OPTIONS_CACHE["raw"]


def simulation_options(client: BrainClient | None = None, instrument_type: str = "EQUITY") -> Dict[str, Any]:
    """Parsed simulation options:
    {
      "types": ["REGULAR", "REGION_AGNOSTIC", ...],
      "regions": {"USA": {"universes": [...], "delays": [1, 0], "neutralizations": [...]}, ...},
      "choices": {"pasteurization": [...], "simulationMode": ["FULL","QUICK"], "language": [...], ...},
      "ranges": {"decay": [0, 512], "truncation": [0, 1], "lookback": [...], "testPeriod": [...], ...},
      "required": [...settings fields that are required...]
    }
    """
    raw = raw_simulation_options(client)
    post = raw.get("actions", {}).get("POST", {})
    settings = post.get("settings", {}).get("children", {})
    out: Dict[str, Any] = {
        "types": _values(post.get("type", {}).get("choices")),
        "regions": {},
        "choices": {},
        "ranges": {},
        "required": [k for k, v in settings.items() if v.get("required")],
    }

    def per_region(field: str) -> Dict[str, List[Any]]:
        ch = settings.get(field, {}).get("choices")
        if isinstance(ch, dict):
            node = ch.get("instrumentType", {}).get(instrument_type, {})
            node = node.get("region", node) if isinstance(node, dict) else {}
            return {r: _values(v) for r, v in node.items()} if isinstance(node, dict) else {}
        return {}

    regions = _values(
        (settings.get("region", {}).get("choices") or {}).get("instrumentType", {}).get(instrument_type, [])
    )
    unis, delays, neuts = per_region("universe"), per_region("delay"), per_region("neutralization")
    for r in regions:
        out["regions"][r] = {
            "universes": unis.get(r, []),
            "delays": delays.get(r, []),
            "neutralizations": neuts.get(r, []),
        }
    for name, spec in settings.items():
        if name in ("region", "universe", "delay", "neutralization"):
            continue
        ch = spec.get("choices")
        if isinstance(ch, list):
            out["choices"][name] = _values(ch)
        if "minValue" in spec or "maxValue" in spec:
            out["ranges"][name] = [spec.get("minValue"), spec.get("maxValue")]
        if spec.get("type") in ("boolean",):
            out["choices"][name] = [True, False]
        if "default" in spec:
            out.setdefault("defaults", {})[name] = spec["default"]
    return out


def list_regions(client: BrainClient | None = None) -> Dict[str, Dict[str, List[Any]]]:
    """{region: {universes, delays, neutralizations}}"""
    return simulation_options(client)["regions"]


def validate_settings(settings: Dict[str, Any], client: BrainClient | None = None) -> List[str]:
    """Return a list of human-readable problems (empty list = OK) for a settings dict."""
    opts = simulation_options(client, settings.get("instrumentType", "EQUITY"))
    errs: List[str] = []
    region = settings.get("region")
    reg = opts["regions"].get(region)
    if reg is None:
        return [f"region '{region}' not available; choose from {sorted(opts['regions'])}"]
    if reg["universes"] and settings.get("universe") not in reg["universes"]:
        errs.append(f"universe '{settings.get('universe')}' invalid for {region}; choose from {reg['universes']}")
    if reg["delays"] and settings.get("delay") not in reg["delays"]:
        errs.append(f"delay {settings.get('delay')} invalid for {region}; choose from {reg['delays']}")
    if reg["neutralizations"] and settings.get("neutralization") not in reg["neutralizations"]:
        errs.append(
            f"neutralization '{settings.get('neutralization')}' invalid for {region}; choose from {reg['neutralizations']}"
        )
    for name, allowed in opts["choices"].items():
        if name in settings and allowed and settings[name] not in allowed:
            errs.append(f"{name}={settings[name]!r} invalid; choose from {allowed}")
    for name, (lo, hi) in opts["ranges"].items():
        v = settings.get(name)
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            if (lo is not None and v < lo) or (hi is not None and v > hi):
                errs.append(f"{name}={v} out of range [{lo}, {hi}]")
    return errs


# ------------------------------------------------------------------ operators
def list_operators(
    client: BrainClient | None = None,
    category: str | None = None,
    scope: str | None = None,
    search: str | None = None,
    use_cache: bool = True,
    cache_hours: float = 24.0,
) -> List[Dict[str, Any]]:
    """GET /operators -> [{name, category, scope, definition, description, documentation, level}].
    Cached on disk for `cache_hours`. Filter by category (e.g. 'Time Series'), scope
    ('REGULAR'/'COMBO'/'SELECTION') or a case-insensitive search over name/definition/description."""
    c = client or get_client()
    cache = c.cache_dir / "operators.json"
    ops = None
    if use_cache and cache.exists() and time.time() - cache.stat().st_mtime < cache_hours * 3600:
        try:
            ops = json.loads(cache.read_text(encoding="utf-8"))
        except ValueError:
            ops = None
    if ops is None:
        ops = c.get("/operators")
        cache.write_text(json.dumps(ops, ensure_ascii=False), encoding="utf-8")
    if category:
        ops = [o for o in ops if str(o.get("category", "")).lower() == category.lower()]
    if scope:
        ops = [o for o in ops if scope.upper() in (o.get("scope") or [])]
    if search:
        q = search.lower()
        ops = [
            o for o in ops
            if q in f"{o.get('name', '')} {o.get('definition', '')} {o.get('description', '')}".lower()
        ]
    return ops


def operator_names(client: BrainClient | None = None, scope: str | None = "REGULAR") -> List[str]:
    return [o["name"] for o in list_operators(client, scope=scope)]


def operator_doc(name: str, client: BrainClient | None = None) -> Dict[str, Any] | None:
    """Operator entry plus its documentation page content (if the operator has one)."""
    c = client or get_client()
    op = next((o for o in list_operators(c) if o.get("name") == name), None)
    if not op:
        return None
    doc_path = op.get("documentation")
    if doc_path:
        try:
            op = {**op, "documentationContent": c.get(doc_path)}
        except Exception:
            pass
    return op


# ------------------------------------------------------------------ account-level metadata
def account_simulation_defaults(client: BrainClient | None = None) -> Dict[str, Any]:
    """GET /users/{id}/settings/simulation - the account's default simulation settings."""
    c = client or get_client()
    if "defaults" not in _OPTIONS_CACHE:
        _OPTIONS_CACHE["defaults"] = c.get(f"/users/{c.user_id}/settings/simulation")
    return dict(_OPTIONS_CACHE["defaults"])


def permissions(client: BrainClient | None = None) -> List[str]:
    """e.g. MULTI_SIMULATION, QUICK_MODE, REGION_AGNOSTIC, VISUALIZATION, CONSULTANT, BRAIN_LABS..."""
    c = client or get_client()
    info = c.auth_status() or c.authenticate()
    return list(info.get("permissions") or [])
