from __future__ import annotations

import json
from typing import Any

import config


def fetch_json(
    url: str,
    params: dict[str, str | int | float] | None = None,
    timeout: int = 20,
) -> Any:
    """Fetch JSON with requests when available, urllib as a small fallback."""
    try:
        import requests

        response = requests.get(
            url,
            params=params,
            timeout=timeout,
            headers={"User-Agent": "QuillScout/0.1"},
            proxies=_requests_proxies(),
        )
        response.raise_for_status()
        return response.json()
    except ModuleNotFoundError:
        return _fetch_json_urllib(url, params, timeout)


def fetch_text(url: str, timeout: int = 20, user_agent: str = "QuillScout/0.1") -> str:
    request = _build_request(url, user_agent)
    with _urlopen(request, timeout=timeout) as response:
        return response.read().decode("utf-8", errors="replace")


def _fetch_json_urllib(
    url: str,
    params: dict[str, str | int | float] | None,
    timeout: int,
) -> Any:
    from urllib.parse import urlencode
    from urllib.request import Request, urlopen

    if params:
        separator = "&" if "?" in url else "?"
        url = f"{url}{separator}{urlencode(params)}"

    request = _build_request(url)
    with _urlopen(request, timeout=timeout) as response:
        body = response.read().decode("utf-8")
    return json.loads(body)


def _build_request(url: str, user_agent: str = "QuillScout/0.1") -> Any:
    from urllib.request import Request

    return Request(url, headers={"User-Agent": user_agent})


def _urlopen(request: Any, timeout: int) -> Any:
    from urllib.request import ProxyHandler, build_opener, urlopen

    proxy_url = getattr(config, "PROXY_URL", "")
    if not proxy_url:
        return urlopen(request, timeout=timeout)

    opener = build_opener(ProxyHandler({"http": proxy_url, "https": proxy_url}))
    return opener.open(request, timeout=timeout)


def _requests_proxies() -> dict[str, str] | None:
    proxy_url = getattr(config, "PROXY_URL", "")
    if not proxy_url:
        return None
    return {"http": proxy_url, "https": proxy_url}
