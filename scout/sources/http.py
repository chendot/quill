from __future__ import annotations

import json
from typing import Any


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
        )
        response.raise_for_status()
        return response.json()
    except ModuleNotFoundError:
        return _fetch_json_urllib(url, params, timeout)


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

    request = Request(url, headers={"User-Agent": "QuillScout/0.1"})
    with urlopen(request, timeout=timeout) as response:
        body = response.read().decode("utf-8")
    return json.loads(body)
