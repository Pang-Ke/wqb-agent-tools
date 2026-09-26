"""BRAIN community forum & help-center articles (support.worldquantbrain.com, Zendesk).

Access is obtained with the BRAIN session via SSO (GET /authentication/support?return_to=...),
then the Zendesk JSON API v2 is used directly - no browser needed (HTML pages are behind
Cloudflare, the JSON API is not)."""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import quote

from .client import BrainClient, BrainError, get_client
from .utils import html_to_text

SUPPORT = "https://support.worldquantbrain.com"
CN_CONSULTANT_TOPIC = 18910956638743      # 顾问专属中文论坛 (used by the original platform crawler)
_BROWSER_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0 Safari/537.36"


class ForumClient:
    def __init__(self, client: BrainClient | None = None) -> None:
        self.brain = client or get_client()
        self._lock = threading.Lock()
        self._ready = False

    # ------------------------------------------------------------------ session
    def login(self) -> Dict[str, Any]:
        """SSO into the support site using the BRAIN session. Returns the Zendesk user (id, name)."""
        with self._lock:
            self.brain.authenticate()
            s = self.brain.session
            url = self.brain.url("/authentication/support?return_to=" + quote(f"{SUPPORT}/hc/en-us", safe=""))
            # Zendesk's /access/jwt answers 401 to 'Accept: application/json' -> use a browser Accept header
            s.get(url, headers={"User-Agent": _BROWSER_UA, "Accept": "text/html,application/xhtml+xml,*/*;q=0.8"},
                  timeout=60, allow_redirects=True)
            r = s.get(f"{SUPPORT}/api/v2/users/me.json", headers={"User-Agent": _BROWSER_UA}, timeout=60)
            user = (r.json() or {}).get("user", {}) if r.ok else {}
            if not user or not user.get("id"):
                raise BrainError("Forum SSO failed (Zendesk session not established)", r.status_code, r.text[:300])
            self._ready = True
            return {"id": user.get("id"), "name": user.get("name")}

    def get(self, path: str, params: Dict[str, Any] | None = None) -> Any:
        """GET a Zendesk API path (e.g. '/api/v2/community/posts.json'); re-SSO on 401/403."""
        if not self._ready:
            self.login()
        url = path if path.startswith("http") else SUPPORT + path
        for attempt in range(6):
            r = self.brain.session.get(url, params=params, headers={"User-Agent": _BROWSER_UA}, timeout=60)
            if r.status_code in (401, 403) and attempt == 0:
                self._ready = False
                self.login()
                continue
            if r.status_code == 429:
                time.sleep(float(r.headers.get("Retry-After") or 5))
                continue
            if r.status_code >= 500:
                time.sleep(2 + attempt * 2)
                continue
            if r.status_code >= 400:
                raise BrainError(f"GET {path} -> {r.status_code}: {r.text[:300]}", r.status_code)
            return r.json()
        raise BrainError(f"GET {path} failed after retries")

    # ------------------------------------------------------------------ community
    def topics(self) -> List[Dict[str, Any]]:
        """All community topics (sub-forums): id, name, description, follower_count, html_url."""
        out, page = [], f"{SUPPORT}/api/v2/community/topics.json?per_page=100"
        while page:
            data = self.get(page)
            out += [{k: t.get(k) for k in ("id", "name", "description", "follower_count", "html_url", "updated_at")}
                    for t in data.get("topics", [])]
            page = data.get("next_page")
        return out

    def posts(
        self,
        topic_id: int | None = None,
        sort_by: str = "created_at",
        limit: int = 30,
        text: bool = True,
        max_chars: int | None = 4000,
    ) -> List[Dict[str, Any]]:
        """Latest posts, optionally within one topic.
        sort_by: 'created_at' | 'recent_activity' | 'votes' | 'comments' | 'edited_at'."""
        path = f"/api/v2/community/topics/{topic_id}/posts.json" if topic_id else "/api/v2/community/posts.json"
        out: List[Dict[str, Any]] = []
        page = 1
        while len(out) < limit:
            data = self.get(path, {"sort_by": sort_by, "per_page": min(100, limit), "page": page})
            batch = data.get("posts", [])
            out += [self._post(p, text, max_chars) for p in batch]
            if not data.get("next_page") or not batch:
                break
            page += 1
        return out[:limit]

    def post(self, post_id: int, comments: bool = True, text: bool = True) -> Dict[str, Any]:
        """One post with full body (and its comments)."""
        p = self._post(self.get(f"/api/v2/community/posts/{post_id}.json")["post"], text, None)
        if comments:
            p["comments"] = self.comments(post_id, text=text)
        return p

    def comments(self, post_id: int, text: bool = True, limit: int = 500) -> List[Dict[str, Any]]:
        out, page = [], 1
        while len(out) < limit:
            data = self.get(f"/api/v2/community/posts/{post_id}/comments.json", {"per_page": 100, "page": page})
            for cmt in data.get("comments", []):
                out.append({
                    "id": cmt.get("id"), "author_id": cmt.get("author_id"), "created_at": cmt.get("created_at"),
                    "vote_sum": cmt.get("vote_sum"), "official": cmt.get("official"),
                    "body": html_to_text(cmt.get("body")) if text else cmt.get("body"),
                })
            if not data.get("next_page"):
                break
            page += 1
        return out

    def search_posts(self, query: str, topic_id: int | None = None, limit: int = 25, text: bool = True,
                     max_chars: int | None = 4000) -> List[Dict[str, Any]]:
        """Full-text search over community posts."""
        params: Dict[str, Any] = {"query": query, "per_page": min(100, limit)}
        if topic_id:
            params["topic"] = topic_id
        data = self.get("/api/v2/help_center/community_posts/search.json", params)
        return [self._post(p, text, max_chars) for p in data.get("results", [])][:limit]

    def crawl_topic(
        self,
        topic_id: int = CN_CONSULTANT_TOPIC,
        out_dir: str | Path | None = None,
        limit: int = 50,
        since_id: int | None = None,
        with_comments: bool = True,
    ) -> Dict[str, Any]:
        """Fetch newest posts of a topic (stop at `since_id` if given) and optionally save each as JSON
        into out_dir/{post_id}.json. Replaces the original Playwright-based forum crawler."""
        posts = self.posts(topic_id, sort_by="created_at", limit=limit, text=True, max_chars=None)
        if since_id:
            cut = [p for p in posts if int(p["id"]) > int(since_id)]
            posts = cut
        if with_comments:
            for p in posts:
                if p.get("comment_count"):
                    p["comments"] = self.comments(p["id"])
        if out_dir:
            d = Path(out_dir)
            d.mkdir(parents=True, exist_ok=True)
            for p in posts:
                (d / f"{p['id']}.json").write_text(json.dumps(p, ensure_ascii=False, indent=1), encoding="utf-8")
        return {"topic_id": topic_id, "count": len(posts), "newest_id": posts[0]["id"] if posts else since_id,
                "posts": posts, "saved_to": str(out_dir) if out_dir else None}

    # ------------------------------------------------------------------ help center
    def search_articles(self, query: str, limit: int = 25, text: bool = True, max_chars: int | None = 4000,
                        locale: str | None = None) -> List[Dict[str, Any]]:
        params: Dict[str, Any] = {"query": query, "per_page": min(100, limit)}
        if locale:
            params["locale"] = locale
        data = self.get("/api/v2/help_center/articles/search.json", params)
        return [self._article(a, text, max_chars) for a in data.get("results", [])][:limit]

    def articles(self, section_id: int | None = None, category_id: int | None = None, sort_by: str = "updated_at",
                 limit: int = 50, locale: str = "en-us", text: bool = False) -> List[Dict[str, Any]]:
        """List help-center articles (optionally within a section/category)."""
        if section_id:
            path = f"/api/v2/help_center/{locale}/sections/{section_id}/articles.json"
        elif category_id:
            path = f"/api/v2/help_center/{locale}/categories/{category_id}/articles.json"
        else:
            path = f"/api/v2/help_center/{locale}/articles.json"
        out, page = [], 1
        while len(out) < limit:
            data = self.get(path, {"sort_by": sort_by, "sort_order": "desc", "per_page": min(100, limit), "page": page})
            out += [self._article(a, text, 400) for a in data.get("articles", [])]
            if not data.get("next_page"):
                break
            page += 1
        return out[:limit]

    def article(self, article_id: int, text: bool = True, attachments: bool = True) -> Dict[str, Any]:
        a = self._article(self.get(f"/api/v2/help_center/articles/{article_id}.json")["article"], text, None)
        if attachments:
            att = self.get(f"/api/v2/help_center/articles/{article_id}/attachments.json").get("article_attachments", [])
            a["attachments"] = [{k: x.get(k) for k in ("id", "file_name", "content_url", "content_type", "size")} for x in att]
        return a

    def categories(self, locale: str = "en-us") -> List[Dict[str, Any]]:
        data = self.get(f"/api/v2/help_center/{locale}/categories.json", {"per_page": 100})
        return [{k: c.get(k) for k in ("id", "name", "description", "html_url")} for c in data.get("categories", [])]

    def sections(self, category_id: int | None = None, locale: str = "en-us") -> List[Dict[str, Any]]:
        path = (f"/api/v2/help_center/{locale}/categories/{category_id}/sections.json" if category_id
                else f"/api/v2/help_center/{locale}/sections.json")
        out, page = [], path + "?per_page=100"
        while page:
            data = self.get(page)
            out += [{k: s.get(k) for k in ("id", "name", "category_id", "description", "html_url")} for s in data.get("sections", [])]
            page = data.get("next_page")
        return out

    # ------------------------------------------------------------------ shaping
    @staticmethod
    def _post(p: Dict[str, Any], text: bool, max_chars: int | None) -> Dict[str, Any]:
        body = html_to_text(p.get("details")) if text else p.get("details")
        if max_chars and body and len(body) > max_chars:
            body = body[:max_chars] + " ..."
        return {
            "id": p.get("id"), "title": p.get("title") or p.get("name"), "topic_id": p.get("topic_id"),
            "author_id": p.get("author_id"), "created_at": p.get("created_at"), "updated_at": p.get("updated_at"),
            "vote_sum": p.get("vote_sum"), "comment_count": p.get("comment_count"), "follower_count": p.get("follower_count"),
            "featured": p.get("featured"), "status": p.get("status"), "html_url": p.get("html_url"), "body": body,
        }

    @staticmethod
    def _article(a: Dict[str, Any], text: bool, max_chars: int | None) -> Dict[str, Any]:
        body = html_to_text(a.get("body")) if text else None
        if max_chars and body and len(body) > max_chars:
            body = body[:max_chars] + " ..."
        out = {k: a.get(k) for k in ("id", "title", "section_id", "created_at", "updated_at", "vote_sum",
                                     "label_names", "html_url", "promoted")}
        if body is not None:
            out["body"] = body
        return out


_forum: ForumClient | None = None


def get_forum(client: BrainClient | None = None) -> ForumClient:
    global _forum
    if _forum is None or (client is not None and _forum.brain is not client):
        _forum = ForumClient(client)
    return _forum
