import asyncio
from dataclasses import dataclass
from typing import Any

import httpx


@dataclass
class ExternalAPIError(Exception):
    service: str
    kind: str
    message: str
    status_code: int | None = None

    def __str__(self) -> str:
        status = f" status={self.status_code}" if self.status_code is not None else ""
        return f"{self.service}:{self.kind}:{self.message}{status}"


DEFAULT_TIMEOUT = 10.0
DEFAULT_RETRIES = 1
_ASYNC_CLIENT: httpx.AsyncClient | None = None
_ASYNC_CLIENT_LOOP: asyncio.AbstractEventLoop | None = None
_ASYNC_CLIENT_LOCK = asyncio.Lock()


async def _get_async_client() -> httpx.AsyncClient:
    global _ASYNC_CLIENT, _ASYNC_CLIENT_LOOP
    loop = asyncio.get_running_loop()
    async with _ASYNC_CLIENT_LOCK:
        if _ASYNC_CLIENT is not None and _ASYNC_CLIENT_LOOP is not loop:
            await _ASYNC_CLIENT.aclose()
            _ASYNC_CLIENT = None
            _ASYNC_CLIENT_LOOP = None

        if _ASYNC_CLIENT is None or _ASYNC_CLIENT.is_closed:
            _ASYNC_CLIENT = httpx.AsyncClient(
                follow_redirects=True,
                trust_env=False,
                limits=httpx.Limits(max_connections=40, max_keepalive_connections=20, keepalive_expiry=30.0),
            )
            _ASYNC_CLIENT_LOOP = loop
        return _ASYNC_CLIENT


async def close_http_client() -> None:
    global _ASYNC_CLIENT, _ASYNC_CLIENT_LOOP
    async with _ASYNC_CLIENT_LOCK:
        if _ASYNC_CLIENT is not None and not _ASYNC_CLIENT.is_closed:
            await _ASYNC_CLIENT.aclose()
        _ASYNC_CLIENT = None
        _ASYNC_CLIENT_LOOP = None


async def request_json(
    *,
    service: str,
    method: str,
    url: str,
    params: dict[str, Any] | None = None,
    json_data: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    timeout: float = DEFAULT_TIMEOUT,
    retries: int = DEFAULT_RETRIES,
) -> Any:
    delay = 0.7
    last_error: ExternalAPIError | None = None

    for attempt in range(retries + 1):
        try:
            client = await _get_async_client()
            response = await client.request(
                method=method,
                url=url,
                params=params,
                json=json_data,
                headers=headers,
                timeout=timeout,
            )

            if response.status_code == 429:
                raise ExternalAPIError(service=service, kind="rate_limit", message="too many requests", status_code=429)

            response.raise_for_status()
            return response.json()
        except httpx.TimeoutException as exc:
            last_error = ExternalAPIError(service=service, kind="timeout", message=str(exc))
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code if exc.response is not None else None
            last_error = ExternalAPIError(service=service, kind="http", message=str(exc), status_code=status)
        except httpx.RequestError as exc:
            last_error = ExternalAPIError(service=service, kind="network", message=str(exc))
        except ValueError as exc:
            last_error = ExternalAPIError(service=service, kind="parse", message=str(exc))

        if attempt < retries:
            await asyncio.sleep(delay)
            delay = min(delay * 2, 5.0)

    if last_error:
        raise last_error
    raise ExternalAPIError(service=service, kind="unknown", message="unknown request failure")


async def request_text(
    *,
    service: str,
    method: str,
    url: str,
    params: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    timeout: float = DEFAULT_TIMEOUT,
    retries: int = DEFAULT_RETRIES,
) -> str:
    delay = 0.7
    last_error: ExternalAPIError | None = None

    for attempt in range(retries + 1):
        try:
            client = await _get_async_client()
            response = await client.request(
                method=method,
                url=url,
                params=params,
                headers=headers,
                timeout=timeout,
            )

            if response.status_code == 429:
                raise ExternalAPIError(service=service, kind="rate_limit", message="too many requests", status_code=429)

            response.raise_for_status()
            return response.text
        except httpx.TimeoutException as exc:
            last_error = ExternalAPIError(service=service, kind="timeout", message=str(exc))
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code if exc.response is not None else None
            last_error = ExternalAPIError(service=service, kind="http", message=str(exc), status_code=status)
        except httpx.RequestError as exc:
            last_error = ExternalAPIError(service=service, kind="network", message=str(exc))

        if attempt < retries:
            await asyncio.sleep(delay)
            delay = min(delay * 2, 5.0)

    if last_error:
        raise last_error
    raise ExternalAPIError(service=service, kind="unknown", message="unknown request failure")


async def healthcheck_json(service: str, method: str, url: str, **kwargs: Any) -> tuple[bool, str]:
    try:
        await request_json(service=service, method=method, url=url, retries=1, **kwargs)
        return True, "ok"
    except ExternalAPIError as exc:
        return False, f"{exc.kind}:{exc.status_code or '-'}"


async def healthcheck_text(service: str, method: str, url: str, **kwargs: Any) -> tuple[bool, str]:
    try:
        await request_text(service=service, method=method, url=url, retries=1, **kwargs)
        return True, "ok"
    except ExternalAPIError as exc:
        return False, f"{exc.kind}:{exc.status_code or '-'}"
