"""Low-level HTTP client for the WorldQuant BRAIN API.

Handles authentication (incl. biometric/persona flow), cookie persistence,
retries (429 / 5xx / 401 re-auth), Retry-After polling and pagination.
Everything else in the package is built on top of `BrainClient`.
"""
from __future__ import annotations

import json
import os
import random
import threading
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional
from urllib.parse import urljoin

from ._http import RequestException, Response, Session

BASE_URL = "https://api.worldquantbrain.com"
PACKAGE_ROOT = Path(__file__).resolve().parents[1]          # the toolkit folder (agent_tools)
CACHE_DIR = Path(os.getenv("WQB_CACHE_DIR") or (PACKAGE_ROOT / ".cache"))
USER_AGENT = "wqb-agent-tools/1.0 (python-urllib)"


class BrainError(RuntimeError):
    """Raised for non-recoverable API errors."""

    def __init__(self, message: str, status: int | None = None, payload: Any = None):
        super().__init__(message)
        self.status = status
        self.payload = payload


class BrainAuthError(BrainError):
    pass


class PersonaRequired(BrainAuthError):
    """Biometric sign-in is enabled: open `url` in a browser, then call
    `client.complete_persona(url)` (or run `wqb.py login --wait`)."""

    def __init__(self, url: str):
        super().__init__(f"Biometric authentication required. Open this URL in a browser: {url}", 401)
        self.url = url


# --------------------------------------------------------------------------- credentials
def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _creds_from_obj(obj: Any) -> tuple[str, str] | None:
    if isinstance(obj, (list, tuple)) and len(obj) >= 2:
        return str(obj[0]), str(obj[1])
    if isinstance(obj, dict):
        if isinstance(obj.get("credentials"), dict):
            obj = obj["credentials"]
        email, password = obj.get("email") or obj.get("username"), obj.get("password")
        if email and password:
            return str(email), str(password)
    return None


def resolve_credentials(email: str | None = None, password: str | None = None) -> tuple[str, str]:
    """Credential lookup order:
    1. explicit arguments
    2. env WQB_EMAIL / WQB_PASSWORD (also WQ_BRAIN_EMAIL / WQ_BRAIN_PASSWORD)
    3. file named by env WQB_CREDENTIALS_FILE
    4. <toolkit folder>/credentials.json  ({"email": ..., "password": ...} or ["email", "password"])
    5. ~/.brain_credentials               (official format: ["email", "password"])
    """
    if email and password:
        return email, password
    env_e = os.getenv("WQB_EMAIL") or os.getenv("WQ_BRAIN_EMAIL")
    env_p = os.getenv("WQB_PASSWORD") or os.getenv("WQ_BRAIN_PASSWORD")
    if env_e and env_p:
        return env_e, env_p
    candidates = [PACKAGE_ROOT / "credentials.json", Path.home() / ".brain_credentials"]
    if os.getenv("WQB_CREDENTIALS_FILE"):
        candidates.insert(0, Path(os.environ["WQB_CREDENTIALS_FILE"]).expanduser())
    for path in candidates:
        creds = _creds_from_obj(_load_json(path)) if path.exists() else None
        if creds:
            return creds
    raise BrainAuthError(
        f"No BRAIN credentials found. Set WQB_EMAIL/WQB_PASSWORD or create {PACKAGE_ROOT / 'credentials.json'}"
    )


# --------------------------------------------------------------------------- client
class BrainClient:
    def __init__(
        self,
        email: str | None = None,
        password: str | None = None,
        base_url: str = BASE_URL,
        cache_dir: Path | str | None = None,
        timeout: float = 60.0,
        verbose: bool = False,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self._email, self._password = email, password
        self.timeout = timeout
        self.verbose = verbose
        self.cache_dir = Path(cache_dir) if cache_dir else CACHE_DIR
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.cookie_file = self.cache_dir / "session_cookies.json"
        self.session = Session()
        self.session.headers.update({"User-Agent": USER_AGENT, "Accept": "application/json"})
        self._auth_lock = threading.RLock()
        self._auth_info: Dict[str, Any] | None = None
        self.last_ratelimit: Dict[str, str] = {}
        self._load_cookies()

    # ------------------------------------------------------------------ utils
    def log(self, *args: Any) -> None:
        if self.verbose:
            print("[wqb]", *args, flush=True)

    def url(self, path: str) -> str:
        if path.startswith("http://") or path.startswith("https://"):
            return path.replace("http://api.worldquantbrain.com", "https://api.worldquantbrain.com")
        return f"{self.base_url}/{path.lstrip('/')}"

    def _load_cookies(self) -> None:
        data = _load_json(self.cookie_file)
        if isinstance(data, list):
            for c in data:
                try:
                    self.session.cookies.set(c["name"], c["value"], domain=c.get("domain"), path=c.get("path", "/"))
                except Exception:
                    continue

    def _save_cookies(self) -> None:
        items = [
            {"name": c.name, "value": c.value, "domain": c.domain, "path": c.path}
            for c in self.session.cookies
        ]
        try:
            self.cookie_file.write_text(json.dumps(items), encoding="utf-8")
        except OSError:
            pass

    # ------------------------------------------------------------------ auth
    def auth_status(self) -> Dict[str, Any] | None:
        """GET /authentication -> {'user':{'id'}, 'token':{'expiry'}, 'permissions':[...]} or None."""
        try:
            r = self.session.get(self.url("/authentication"), timeout=self.timeout)
        except RequestException:
            return None
        if r.status_code == 200:
            try:
                self._auth_info = r.json()
            except ValueError:
                return None
            return self._auth_info
        return None

    def authenticate(self, force: bool = False, expiry: int | None = None) -> Dict[str, Any]:
        """Sign in with basic auth (POST /authentication). Reuses a valid cookie unless force=True."""
        with self._auth_lock:
            if not force:
                info = self.auth_status()
                if info and float(info.get("token", {}).get("expiry", 0)) > 120:
                    return info
            email, password = resolve_credentials(self._email, self._password)
            body = {"expiry": int(expiry)} if expiry else None
            last: Response | None = None
            for attempt in range(6):
                try:
                    r = self.session.post(
                        self.url("/authentication"), auth=(email, password), json=body, timeout=self.timeout
                    )
                except RequestException as exc:
                    self.log("auth network error", exc)
                    time.sleep(min(3 + attempt * 2, 15))
                    continue
                last = r
                if r.status_code in (200, 201):
                    self._auth_info = r.json()
                    self._save_cookies()
                    return self._auth_info
                if r.status_code == 401 and r.headers.get("WWW-Authenticate", "").lower() == "persona":
                    raise PersonaRequired(urljoin(r.url, r.headers.get("Location", "")))
                if r.status_code == 401:
                    raise BrainAuthError(f"Invalid credentials: {r.text[:300]}", 401, r.text)
                if r.status_code == 429 or r.status_code >= 500:
                    time.sleep(_retry_after(r, 5 + attempt * 3))
                    continue
                break
            raise BrainAuthError(
                f"Authentication failed: {last.status_code if last is not None else 'network'} "
                f"{last.text[:300] if last is not None else ''}"
            )

    def complete_persona(self, url: str) -> Dict[str, Any]:
        """Call after finishing biometric verification in the browser."""
        r = self.session.post(url, timeout=self.timeout)
        if r.status_code not in (200, 201):
            raise BrainAuthError(f"Persona completion failed: {r.status_code} {r.text[:300]}", r.status_code)
        self._save_cookies()
        return self.auth_status() or {}

    def logout(self) -> bool:
        r = self.session.delete(self.url("/authentication"), timeout=self.timeout)
        self.session.cookies.clear()
        self._save_cookies()
        return r.status_code in (200, 204)

    @property
    def user_id(self) -> str:
        info = self._auth_info or self.authenticate()
        return info["user"]["id"]

    @property
    def permissions(self) -> List[str]:
        info = self._auth_info or self.authenticate()
        return list(info.get("permissions") or [])

    # ------------------------------------------------------------------ requests
    def request(
        self,
        method: str,
        path: str,
        *,
        params: Dict[str, Any] | List[tuple] | None = None,
        json_body: Any = None,
        headers: Dict[str, str] | None = None,
        max_retries: int = 8,
        ok_statuses: Iterable[int] | None = None,
        raise_on_error: bool = True,
    ) -> Response:
        """Authenticated request with retry on network errors / 429 / 5xx and re-auth on 401."""
        if self._auth_info is None:
            self.authenticate()
        reauthed = False
        last: Response | None = None
        for attempt in range(max_retries):
            try:
                r = self.session.request(
                    method.upper(), self.url(path), params=params, json=json_body,
                    headers=headers, timeout=self.timeout,
                )
            except RequestException as exc:
                self.log(f"{method} {path} network error: {exc}")
                time.sleep(min(2 + attempt * 2, 20))
                continue
            last = r
            rl = {k.lower(): v for k, v in r.headers.items() if k.lower().startswith("x-ratelimit")}
            if rl:
                self.last_ratelimit = rl
            if r.status_code == 401 and not reauthed:
                reauthed = True
                self.authenticate(force=True)
                continue
            if r.status_code == 429:
                wait = _retry_after(r, 3 + attempt * 2) + random.uniform(0, 0.5)
                self.log(f"429 on {path}: {r.text[:120]} - sleeping {wait:.1f}s")
                time.sleep(wait)
                continue
            if r.status_code >= 500 and attempt < max_retries - 1:
                time.sleep(min(2 + attempt * 3, 20))
                continue
            break
        if last is None:
            raise BrainError(f"{method} {path}: network failure")
        good = set(ok_statuses) if ok_statuses else None
        failed = (last.status_code not in good) if good else last.status_code >= 400
        if failed and raise_on_error:
            raise BrainError(f"{method} {path} -> {last.status_code}: {last.text[:500]}", last.status_code, _safe_json(last))
        return last

    def get(self, path: str, params: Any = None, **kw: Any) -> Any:
        return _safe_json(self.request("GET", path, params=params, **kw))

    def options(self, path: str, **kw: Any) -> Any:
        return _safe_json(self.request("OPTIONS", path, **kw))

    def post(self, path: str, json_body: Any = None, params: Any = None, **kw: Any) -> Any:
        return _safe_json(self.request("POST", path, json_body=json_body, params=params, **kw))

    def patch(self, path: str, json_body: Any = None, **kw: Any) -> Any:
        return _safe_json(self.request("PATCH", path, json_body=json_body, **kw))

    def delete(self, path: str, **kw: Any) -> Any:
        return _safe_json(self.request("DELETE", path, **kw))

    def poll(
        self,
        path: str,
        *,
        params: Any = None,
        timeout: float = 1800,
        headers: Dict[str, str] | None = None,
        min_interval: float = 1.0,
        on_progress: Any = None,
    ) -> Response:
        """GET repeatedly while the server answers with a `Retry-After` header
        (used by simulations, /check, correlations, recordsets, submit ...)."""
        deadline = time.time() + timeout
        while True:
            r = self.request("GET", path, params=params, headers=headers, raise_on_error=False)
            ra = r.headers.get("Retry-After")
            if r.status_code < 400 and ra is not None and float(ra or 0) > 0:
                if on_progress:
                    try:
                        on_progress(_safe_json(r))
                    except Exception:
                        pass
                if time.time() > deadline:
                    raise BrainError(f"Timed out polling {path}", 408)
                time.sleep(max(min_interval, float(ra)))
                continue
            return r

    def paginate(
        self,
        path: str,
        params: Dict[str, Any] | List[tuple] | None = None,
        *,
        limit: int | None = None,
        page_size: int = 100,
        results_key: str = "results",
    ) -> List[Any]:
        """Follow limit/offset pagination. `limit=None` fetches everything."""
        out: List[Any] = []
        offset = 0
        base = list(params.items()) if isinstance(params, dict) else list(params or [])
        base = [(k, v) for k, v in base if k not in ("limit", "offset") and v is not None]
        while True:
            size = page_size if limit is None else max(1, min(page_size, limit - len(out)))
            data = self.get(path, params=base + [("limit", size), ("offset", offset)])
            items = data.get(results_key, []) if isinstance(data, dict) else (data or [])
            out.extend(items)
            offset += len(items)
            total = data.get("count") if isinstance(data, dict) else None
            if not items or (limit is not None and len(out) >= limit):
                break
            if total is not None and offset >= total:
                break
            if isinstance(data, dict) and not data.get("next") and total is None:
                break
        return out if limit is None else out[:limit]


# --------------------------------------------------------------------------- helpers
def _retry_after(r: Response, fallback: float) -> float:
    try:
        return max(1.0, min(float(r.headers.get("Retry-After")), 120.0))
    except (TypeError, ValueError):
        return float(min(fallback, 60))


def _safe_json(r: Response) -> Any:
    if not r.content:
        return {} if r.status_code < 400 else None
    try:
        return r.json()
    except ValueError:
        return r.text


_default_client: BrainClient | None = None
_default_lock = threading.Lock()


def get_client(**kwargs: Any) -> BrainClient:
    """Process-wide shared client (lazy). Pass kwargs only on first call to customise."""
    global _default_client
    with _default_lock:
        if _default_client is None or kwargs:
            _default_client = BrainClient(**kwargs)
        return _default_client


def set_client(client: BrainClient) -> None:
    global _default_client
    _default_client = client
