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


def leaderboard_row(user_id: str | None = None, board: str = "leader",
                    client: BrainClient | None = None) -> Optional[Dict[str, Any]]:
    """Your (or any user's) row on a consultant board, in one request (the board accepts a 'user' filter) instead of
    paging through ~14k rows. board: leader (weight / value factor) | genius | power-pool | spc. None if not listed."""
    c = client or get_client()
    uid = user_id or c.user_id
    rows = consultant_board(board, limit=5, client=c, user=uid).get("results") or []
    def row_user(r: Dict[str, Any]) -> Any:
        u = r.get("user")
        return u.get("id") if isinstance(u, dict) else u

    # match explicitly: if the filter were ever ignored, rows[0] would be somebody else
    return next((r for r in rows if row_user(r) == uid), None)


def value_factor(user_id: str | None = None, client: BrainClient | None = None) -> Dict[str, Any]:
    """Value Factor (VF) and Weight Factor from the consultant leaderboard, plus the diversity stats shown next to them.
    VF (0..1, platform average 0.5) is the OS performance of the combination of your recent submissions (rolling
    3 months); it scales base and quarterly payments and refreshes only every 4-6 weeks, so recent submissions show
    up late. See submission_days() for the 20-day rule that resets it."""
    r = leaderboard_row(user_id, "leader", client) or {}
    return {"user": r.get("user"), "value_factor": r.get("valueFactor"), "weight_factor": r.get("weightFactor"),
            "data_fields_used": r.get("dataFieldsUsed"), "submissions": r.get("submissionsCount"),
            "mean_prod_correlation": r.get("meanProdCorrelation"), "mean_self_correlation": r.get("meanSelfCorrelation"),
            "super_alpha_submissions": r.get("superAlphaSubmissionsCount"),
            "daily_osmosis_rank": r.get("dailyOsmosisRank"), "raw": r}


def _us_eastern_offset(now_utc: Any) -> int:
    """UTC offset (hours) of US Eastern at an aware UTC datetime, without a tz database (zoneinfo needs tzdata on
    Windows). DST: second Sunday of March 07:00 UTC -> first Sunday of November 06:00 UTC."""
    from datetime import datetime, timezone

    y = now_utc.year
    mar = datetime(y, 3, 8, 7, tzinfo=timezone.utc)
    nov = datetime(y, 11, 1, 6, tzinfo=timezone.utc)
    start = mar + timedelta(days=(6 - mar.weekday()) % 7)
    end = nov + timedelta(days=(6 - nov.weekday()) % 7)
    return -4 if start <= now_utc < end else -5


def _us_eastern_today() -> date:
    """Today's date on the platform clock (US Eastern)."""
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc)
    return (now + timedelta(hours=_us_eastern_offset(now))).date()


def recent_submissions(days: int = 7, since: str | None = None, client: BrainClient | None = None) -> List[Dict[str, Any]]:
    """Alphas / SuperAlphas you submitted in the last `days` platform days (US Eastern; days=1 -> today only), or since
    a date 'YYYY-MM-DD'. Newest first: {id, date, dateSubmitted, type, region, universe, sharpe, fitness,
    classifications}."""
    from .alphas import list_alphas

    c = client or get_client()
    start = since or (_us_eastern_today() - timedelta(days=max(1, days) - 1)).isoformat()
    # server-side filter needs an ISO datetime with offset; -05:00 is the earlier of EST/EDT midnights (inclusive),
    # the exact day cut is done below on the Eastern-offset timestamps the platform returns
    rows = list_alphas([f"dateSubmitted>={start}T00:00:00-05:00"], stage="OS", order="-dateSubmitted", limit=None,
                       client=c)["alphas"]
    out = []
    for a in rows:
        d = (a.get("dateSubmitted") or "")[:10]
        if d < start:
            continue
        s = a.get("settings") or {}
        out.append({"id": a.get("id"), "date": d, "dateSubmitted": a.get("dateSubmitted"), "type": a.get("type"),
                    "region": s.get("region"), "universe": s.get("universe"), "sharpe": (a.get("is") or {}).get("sharpe"),
                    "fitness": (a.get("is") or {}).get("fitness"),
                    "classifications": [x.get("id") for x in a.get("classifications") or [] if isinstance(x, dict)]})
    return out


def submission_days(window_days: int = 91, min_days: int = 20, client: BrainClient | None = None) -> Dict[str, Any]:
    """Distinct days with at least one submission in the rolling window. The Value Factor resets to its minimum when
    you submit on fewer than `min_days` (20) days in a rolling 3-month window, so spreading submissions over more days
    beats submitting several on one day. Returns {window_start, days, count, min_days, shortfall, at_risk, today}."""
    today = _us_eastern_today()
    start = (today - timedelta(days=window_days - 1)).isoformat()
    subs = recent_submissions(since=start, client=client)
    days = sorted({s["date"] for s in subs})
    return {"window_start": start, "today": today.isoformat(), "days": days, "count": len(days), "min_days": min_days,
            "shortfall": max(0, min_days - len(days)), "at_risk": len(days) < min_days,
            "submitted_today": sum(s["date"] == today.isoformat() for s in subs)}


def account_status(client: BrainClient | None = None) -> Dict[str, Any]:
    """One call for 'how am I doing': genius level and current-quarter stats, value / weight factor, submission-day
    count against the 20-day rule, and today's submissions."""
    c = client or get_client()
    perf = (consultant_summary(client=c).get("performance") or {})
    cur = perf.get("current") or {}
    days = submission_days(client=c)
    return {"genius_level": perf.get("currentLevel"), "best_level": perf.get("bestLevel"),
            "quarter": (cur.get("quarter") or {}).get("name"),
            "quarter_stats": {k: cur.get(k) for k in ("alphaCount", "pyramidCount", "combinedAlphaPerformance",
                                                      "combinedSelectedAlphaPerformance", "combinedPowerPoolAlphaPerformance",
                                                      "operatorAvg", "fieldAvg", "communityActivity", "maxSimulationStreak")},
            "value_factor": {k: v for k, v in value_factor(client=c).items() if k != "raw"},
            "submission_days": {k: days[k] for k in ("window_start", "count", "min_days", "shortfall", "at_risk")},
            "submitted_today": days["submitted_today"], "today": days["today"]}


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
