"""Account & community data: profile, activity stats, diversity/pyramids, streak, consultant/genius summary,
osmosis, messages, teams, competitions, leaderboards, events."""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Dict, List, Optional

from .client import BrainClient, get_client
from .utils import html_to_text, recordset_to_dicts


def me(client: BrainClient | None = None) -> Dict[str, Any]:
    """GET /users/self - full profile (id, level/geniusLevel, onboarding status...)."""
    return (client or get_client()).get("/users/self")


def whoami(client: BrainClient | None = None) -> Dict[str, Any]:
    """Authentication state: user id, token expiry (s), permissions."""
    c = client or get_client()
    return c.auth_status() or c.authenticate()


def user_profile(user_id: str, client: BrainClient | None = None) -> Dict[str, Any]:
    """GET /users/{id}/profile - public profile of any user."""
    return (client or get_client()).get(f"/users/{user_id}/profile")


def activity(name: str, date_from: str | None = None, client: BrainClient | None = None) -> Dict[str, Any]:
    """GET /users/self/activities/{name}.
    name: 'simulations' | 'submissions' | 'base-payment' | 'other-payment' | 'referrals'
    Returns yesterday/current/previous/ytd/total summaries plus daily 'rows'."""
    c = client or get_client()
    path = f"/users/self/activities/{name}"
    if date_from:
        path += f"?date%3E={date_from}"
    data = c.get(path)
    if isinstance(data, dict) and isinstance(data.get("records"), dict):
        data = {**data, "rows": recordset_to_dicts(data["records"])}
        data.pop("records", None)
    return data


def simulation_counts(days: int = 7, client: BrainClient | None = None) -> Dict[str, Any]:
    """Simulated-alpha counts (yesterday / period / ytd / total + daily rows for the last `days`)."""
    return activity("simulations", (date.today() - timedelta(days=days)).isoformat(), client)


def diversity(grouping: str = "region,delay,dataCategory", user: str = "self", client: BrainClient | None = None) -> Dict[str, Any]:
    """GET /users/{id}/activities/diversity - submitted-alpha breakdown by region/delay/data category."""
    return (client or get_client()).get(f"/users/{user}/activities/diversity", params={"grouping": grouping})


def pyramid_alphas(client: BrainClient | None = None, **filters: Any) -> List[Dict[str, Any]]:
    """GET /users/self/activities/pyramid-alphas - your alpha count per (category, region, delay) pyramid."""
    data = (client or get_client()).get("/users/self/activities/pyramid-alphas", params=filters or None)
    return data.get("pyramids", data) if isinstance(data, dict) else data


def pyramid_multipliers(client: BrainClient | None = None) -> List[Dict[str, Any]]:
    """GET /users/self/activities/pyramid-multipliers - current multiplier per (category, region, delay)."""
    data = (client or get_client()).get("/users/self/activities/pyramid-multipliers")
    return data.get("pyramids", data) if isinstance(data, dict) else data


def pyramid_overview(client: BrainClient | None = None) -> List[Dict[str, Any]]:
    """Join of pyramid alpha counts and multipliers - handy to find under-filled, high-multiplier pyramids."""
    c = client or get_client()
    mult = {(p["category"]["id"], p["region"], p["delay"]): p.get("multiplier") for p in pyramid_multipliers(c)}
    rows = []
    for p in pyramid_alphas(c):
        key = (p["category"]["id"], p["region"], p["delay"])
        rows.append({"category": key[0], "region": key[1], "delay": key[2],
                     "alphaCount": p.get("alphaCount"), "multiplier": mult.get(key)})
    return sorted(rows, key=lambda r: (-(r["multiplier"] or 0), r["alphaCount"] or 0))


def streak(client: BrainClient | None = None) -> Dict[str, Any]:
    return (client or get_client()).get("/users/self/streak")


def achievements(client: BrainClient | None = None) -> List[Dict[str, Any]]:
    return (client or get_client()).get("/users/self/achievements")


def consultant_summary(user_id: str | None = None, client: BrainClient | None = None) -> Dict[str, Any]:
    """GET /users/{id}/consultant/summary - genius level, quarter stats, combined performance..."""
    c = client or get_client()
    return c.get(f"/users/{user_id or c.user_id}/consultant/summary")


def osmosis_summary(user_id: str | None = None, client: BrainClient | None = None) -> Dict[str, Any]:
    c = client or get_client()
    return c.get(f"/users/{user_id or c.user_id}/osmosis/summary")


def agreements(client: BrainClient | None = None) -> List[Dict[str, Any]]:
    return (client or get_client()).get("/users/self/agreements")


# ------------------------------------------------------------------ messages
def messages(msg_type: str | None = None, limit: int = 20, text: bool = True, client: BrainClient | None = None) -> List[Dict[str, Any]]:
    """GET /users/self/messages. msg_type: 'ANNOUNCEMENT' | 'NOTIFICATION' | None (both)."""
    params: Dict[str, Any] = {"order": "-dateCreated"}
    if msg_type:
        params["type"] = msg_type.upper()
    rows = (client or get_client()).paginate("/users/self/messages", params, limit=limit, page_size=min(limit, 50))
    if text:
        for m in rows:
            if m.get("description"):
                m["description"] = html_to_text(m["description"])
    return rows


def messages_summary(client: BrainClient | None = None) -> Dict[str, Any]:
    return (client or get_client()).get("/users/self/messages/summary")


# ------------------------------------------------------------------ teams / competitions / boards
def teams(client: BrainClient | None = None) -> List[Dict[str, Any]]:
    return (client or get_client()).paginate("/users/self/teams", limit=None)


def competitions(mine: bool = False, client: BrainClient | None = None) -> List[Dict[str, Any]]:
    """GET /competitions (all visible) or /users/self/competitions (joined)."""
    path = "/users/self/competitions" if mine else "/competitions"
    return (client or get_client()).paginate(path, limit=None, page_size=50)


def competition(competition_id: str, client: BrainClient | None = None) -> Dict[str, Any]:
    return (client or get_client()).get(f"/competitions/{competition_id}")


def competition_board(
    competition_id: str,
    board: str = "leader",
    limit: int = 50,
    offset: int = 0,
    client: BrainClient | None = None,
) -> Dict[str, Any]:
    """GET /competitions/{id}/boards/{board}. board: leader | university | prize | referral | power-pool."""
    return (client or get_client()).get(
        f"/competitions/{competition_id}/boards/{board}", params={"limit": limit, "offset": offset}
    )


def consultant_board(board: str = "genius", limit: int = 50, offset: int = 0, client: BrainClient | None = None,
                     **params: Any) -> Dict[str, Any]:
    """GET /consultant/boards/{board}. board: genius | leader | power-pool | spc."""
    q = {"limit": limit, "offset": offset, **params}
    return (client or get_client()).get(f"/consultant/boards/{board}", params=q)


def competition_levels(client: BrainClient | None = None) -> List[Dict[str, Any]]:
    return (client or get_client()).get("/competition-levels")


def events(limit: int = 50, upcoming_only: bool = False, client: BrainClient | None = None) -> List[Dict[str, Any]]:
    """GET /events - webinars / events."""
    params: Dict[str, Any] = {"order": "start"}
    path = "/events"
    if upcoming_only:
        path += f"?start%3E={date.today().isoformat()}"
    rows = (client or get_client()).paginate(path, params, limit=limit, page_size=min(limit, 100))
    for e in rows:
        if e.get("description"):
            e["description"] = html_to_text(e["description"])
    return rows
