"""Data explorer: data categories, datasets, data fields."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from .client import BrainClient, get_client


def _scope(region: str, delay: int, universe: str, instrument_type: str) -> List[tuple]:
    return [("instrumentType", instrument_type), ("region", region), ("delay", int(delay)), ("universe", universe)]


def data_categories(client: BrainClient | None = None) -> List[Dict[str, Any]]:
    """GET /data-categories -> [{id, name, datasetCount, fieldCount, alphaCount, userCount, valueScore, region, children:[...]}]"""
    return (client or get_client()).get("/data-categories")


def list_datasets(
    region: str = "USA",
    delay: int = 1,
    universe: str = "TOP3000",
    *,
    instrument_type: str = "EQUITY",
    category: str | None = None,
    search: str | None = None,
    order: str | None = None,
    theme: bool | None = None,
    limit: int | None = 50,
    client: BrainClient | None = None,
) -> List[Dict[str, Any]]:
    """GET /data-sets. `limit=None` returns all.
    category: e.g. 'analyst', 'fundamental', 'pv', 'news', 'model', 'option', 'other', 'socialmedia', ...
    order:    e.g. '-valueScore', '-alphaCount', 'alphaCount', '-userCount', '-fieldCount', '-coverage'
    Each dataset has id, name, description, category, subcategory, coverage, dateCoverage,
    valueScore, userCount, alphaCount, fieldCount, pyramidMultiplier, themes, researchPapers."""
    params = _scope(region, delay, universe, instrument_type)
    for k, v in (("category", category), ("search", search), ("order", order)):
        if v:
            params.append((k, v))
    if theme is not None:
        params.append(("theme", str(theme).lower()))
    return (client or get_client()).paginate("/data-sets", params, limit=limit, page_size=50)


def get_dataset(
    dataset_id: str,
    region: str | None = None,
    delay: int | None = None,
    universe: str | None = None,
    *,
    instrument_type: str = "EQUITY",
    client: BrainClient | None = None,
) -> Dict[str, Any]:
    """GET /data-sets/{id} - details incl. per region/delay/universe availability under 'data'."""
    params = []
    if region:
        params = _scope(region, delay if delay is not None else 1, universe or "TOP3000", instrument_type)
    return (client or get_client()).get(f"/data-sets/{dataset_id}", params=params or None)


def search_datasets(
    query: str,
    region: str = "USA",
    delay: int = 1,
    universe: str = "TOP3000",
    *,
    instrument_type: str = "EQUITY",
    client: BrainClient | None = None,
) -> Dict[str, Any]:
    """GET /data-sets/search - semantic search (Data Explorer). Returns {'datasets': [...], ...}."""
    params = [("query", query)] + _scope(region, delay, universe, instrument_type)
    return (client or get_client()).get("/data-sets/search", params=params)


def list_datafields(
    region: str = "USA",
    delay: int = 1,
    universe: str = "TOP3000",
    *,
    dataset_id: str | None = None,
    search: str | None = None,
    field_type: str | None = None,
    category: str | None = None,
    order: str | None = None,
    instrument_type: str = "EQUITY",
    limit: int | None = 100,
    client: BrainClient | None = None,
) -> List[Dict[str, Any]]:
    """GET /data-fields. `limit=None` returns all (server caps un-scoped listings at 10000).
    dataset_id: restrict to one dataset (recommended; e.g. 'pv1', 'fundamental6', 'analyst4')
    search:     keyword/relevance search over id + description
    field_type: 'MATRIX' | 'VECTOR' | 'GROUP' | 'UNIVERSE' | 'SYMBOL' (filtered client-side)
    category:   category id (filtered client-side)
    order:      e.g. '-alphaCount', 'alphaCount', '-userCount', '-coverage', '-dateCoverage'
    Each field: id, description, dataset{id,name}, category, subcategory, type, coverage,
    dateCoverage, userCount, alphaCount, pyramidMultiplier, themes."""
    params = _scope(region, delay, universe, instrument_type)
    if dataset_id:
        params.append(("dataset.id", dataset_id))
    if search:
        params.append(("search", search))
    if order:
        params.append(("order", order))
    if field_type:
        params.append(("type", field_type))
    # type/category are not honoured server-side, so over-fetch and filter locally
    fetch_limit = limit
    if (field_type or category) and limit is not None:
        fetch_limit = None if dataset_id else max(limit * 5, 500)
    rows = (client or get_client()).paginate("/data-fields", params, limit=fetch_limit, page_size=50)
    if field_type:
        rows = [r for r in rows if str(r.get("type", "")).upper() == field_type.upper()]
    if category:
        rows = [r for r in rows if (r.get("category") or {}).get("id") == category]
    return rows if limit is None else rows[:limit]


def get_datafield(
    field_id: str,
    region: str | None = None,
    delay: int | None = None,
    universe: str | None = None,
    *,
    instrument_type: str = "EQUITY",
    client: BrainClient | None = None,
) -> Dict[str, Any]:
    """GET /data-fields/{id} - description, dataset, type and per-universe coverage/alphaCount under 'data'."""
    params = []
    if region:
        params = _scope(region, delay if delay is not None else 1, universe or "TOP3000", instrument_type)
    return (client or get_client()).get(f"/data-fields/{field_id}", params=params or None)


def all_datafield_ids(client: BrainClient | None = None) -> List[str]:
    """GET /data-fields/summary - ids of every data field on the platform (used by the editor)."""
    data = (client or get_client()).get("/data-fields/summary")
    return [d.get("id") for d in data if isinstance(d, dict)]


def request_datafield_visualization(
    field_id: str,
    region: str = "USA",
    delay: int = 1,
    universe: str = "TOP3000",
    *,
    instrument_type: str = "EQUITY",
    client: BrainClient | None = None,
) -> Dict[str, Any]:
    """POST /data-fields/{id}/visualize - asks the platform to build the field's visualization
    (needs VISUALIZATION permission; processed asynchronously, result shows on the platform Data page)."""
    c = client or get_client()
    r = c.request("POST", f"/data-fields/{field_id}/visualize", params=_scope(region, delay, universe, instrument_type))
    return {"status": r.status_code, "accepted": r.status_code in (200, 201, 202), "body": r.text[:500]}


def dataset_fields_table(
    dataset_id: str,
    region: str = "USA",
    delay: int = 1,
    universe: str = "TOP3000",
    *,
    client: BrainClient | None = None,
) -> List[Dict[str, Any]]:
    """Compact table of every field in a dataset: id, type, description, coverage, dateCoverage, alphaCount, userCount."""
    rows = list_datafields(region, delay, universe, dataset_id=dataset_id, limit=None, client=client)
    keys = ("id", "type", "description", "coverage", "dateCoverage", "alphaCount", "userCount", "pyramidMultiplier")
    return [{k: r.get(k) for k in keys} for r in rows]
