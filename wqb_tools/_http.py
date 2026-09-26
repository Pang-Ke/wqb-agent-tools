"""Tiny standard-library HTTP session (replaces `requests`, so the toolkit has zero third-party dependencies).

Implements only what the toolkit needs: persistent cookies, default headers, basic auth, JSON bodies,
query params, optional redirect following, and a requests-like Response object."""
from __future__ import annotations

import base64
import http.client
import http.cookiejar
import json as _json
import socket
import ssl
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, Iterable, Iterator, List, Optional, Tuple


class RequestException(IOError):
    """Network-level failure (DNS, connection reset, timeout...)."""


class CaseInsensitiveDict(dict):
    def __init__(self, items: Iterable[Tuple[str, str]] = ()) -> None:
        super().__init__()
        self._keys: Dict[str, str] = {}
        for k, v in items:
            self[k] = v

    def __setitem__(self, key: str, value: Any) -> None:
        old = self._keys.get(key.lower())
        if old is not None and old != key:
            super().__delitem__(old)
        self._keys[key.lower()] = key
        super().__setitem__(key, value)

    def __getitem__(self, key: str) -> Any:
        return super().__getitem__(self._keys[key.lower()])

    def __contains__(self, key: object) -> bool:
        return isinstance(key, str) and key.lower() in self._keys

    def get(self, key: str, default: Any = None) -> Any:  # type: ignore[override]
        return self[key] if key in self else default


class Response:
    def __init__(self, status: int, headers: Iterable[Tuple[str, str]], content: bytes, url: str,
                 history: List["Response"] | None = None) -> None:
        self.status_code = status
        self.headers = CaseInsensitiveDict(headers)
        self.content = content or b""
        self.url = url
        self.history = history or []

    @property
    def ok(self) -> bool:
        return self.status_code < 400

    @property
    def text(self) -> str:
        return self.content.decode("utf-8", errors="replace")

    def json(self) -> Any:
        return _json.loads(self.text)  # raises ValueError (JSONDecodeError) on bad JSON

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RequestException(f"HTTP {self.status_code} for {self.url}")

    def __repr__(self) -> str:
        return f"<Response [{self.status_code}]>"


class CookieStore:
    """Thin wrapper over http.cookiejar.CookieJar with a requests-like `set` / iteration / clear."""

    def __init__(self) -> None:
        self.jar = http.cookiejar.CookieJar()

    def set(self, name: str, value: str, domain: str | None = None, path: str = "/") -> None:
        domain = domain or ""
        self.jar.set_cookie(http.cookiejar.Cookie(
            version=0, name=name, value=value, port=None, port_specified=False,
            domain=domain, domain_specified=bool(domain), domain_initial_dot=domain.startswith("."),
            path=path or "/", path_specified=True, secure=False, expires=None, discard=False,
            comment=None, comment_url=None, rest={}, rfc2109=False,
        ))

    def clear(self) -> None:
        self.jar.clear()

    def __iter__(self) -> Iterator[http.cookiejar.Cookie]:
        return iter(list(self.jar))

    def __len__(self) -> int:
        return len(list(self.jar))


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: D401
        return None  # makes urllib raise HTTPError(3xx), which we turn into a Response


class _Recorder(urllib.request.HTTPRedirectHandler):
    """Follows redirects (like requests) while recording each hop."""

    def __init__(self) -> None:
        super().__init__()
        self.history: List[Response] = []

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        self.history.append(Response(code, headers.items(), b"", req.full_url))
        new = super().redirect_request(req, fp, code, msg, headers, newurl)
        if new is not None and code in (301, 302, 303):
            new.method = "GET"  # type: ignore[attr-defined]
        return new


def _ssl_context() -> ssl.SSLContext:
    ctx = ssl.create_default_context()
    try:  # use certifi's bundle when present (helps on Pythons without system certs)
        import certifi  # type: ignore

        ctx.load_verify_locations(certifi.where())
    except Exception:
        pass
    return ctx


_SSL = _ssl_context()


def _encode_params(url: str, params: Any) -> str:
    if not params:
        return url
    items = params.items() if isinstance(params, dict) else params
    pairs = [(k, "true" if v is True else "false" if v is False else v) for k, v in items if v is not None]
    if not pairs:
        return url
    query = urllib.parse.urlencode(pairs, doseq=True)
    return url + ("&" if "?" in url else "?") + query


class Session:
    def __init__(self) -> None:
        self.headers: Dict[str, str] = {}
        self.cookies = CookieStore()

    def request(
        self,
        method: str,
        url: str,
        params: Any = None,
        json: Any = None,
        data: bytes | None = None,
        headers: Dict[str, str] | None = None,
        timeout: float | None = 60,
        auth: Tuple[str, str] | None = None,
        allow_redirects: bool = True,
    ) -> Response:
        full_url = _encode_params(url, params)
        hdrs = CaseInsensitiveDict(self.headers.items())
        for k, v in (headers or {}).items():
            hdrs[k] = v
        body = data
        if json is not None:
            body = _json.dumps(json, ensure_ascii=False).encode("utf-8")
            if "Content-Type" not in hdrs:
                hdrs["Content-Type"] = "application/json"
        if body is None and method.upper() in ("POST", "PUT", "PATCH"):
            body = b""
        if auth:
            token = base64.b64encode(f"{auth[0]}:{auth[1]}".encode("utf-8")).decode("ascii")
            hdrs["Authorization"] = f"Basic {token}"
        req = urllib.request.Request(full_url, data=body, headers=dict(hdrs), method=method.upper())

        recorder = _Recorder() if allow_redirects else _NoRedirect()
        opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self.cookies.jar),
            urllib.request.HTTPSHandler(context=_SSL),
            recorder,
        )
        history = recorder.history if isinstance(recorder, _Recorder) else []
        try:
            with opener.open(req, timeout=timeout) as resp:
                return Response(resp.status, resp.headers.items(), resp.read(), resp.geturl(), history)
        except urllib.error.HTTPError as exc:  # 4xx/5xx (and 3xx when not following redirects)
            try:
                content = exc.read()
            except Exception:  # noqa: BLE001
                content = b""
            return Response(exc.code, (exc.headers or {}).items(), content, exc.geturl() or full_url, history)
        except (urllib.error.URLError, socket.timeout, TimeoutError, ConnectionError, http.client.HTTPException,
                ssl.SSLError, OSError) as exc:
            raise RequestException(f"{method} {full_url}: {exc}") from exc

    def get(self, url: str, **kw: Any) -> Response:
        return self.request("GET", url, **kw)

    def post(self, url: str, **kw: Any) -> Response:
        return self.request("POST", url, **kw)

    def patch(self, url: str, **kw: Any) -> Response:
        return self.request("PATCH", url, **kw)

    def delete(self, url: str, **kw: Any) -> Response:
        return self.request("DELETE", url, **kw)

    def options(self, url: str, **kw: Any) -> Response:
        return self.request("OPTIONS", url, **kw)
