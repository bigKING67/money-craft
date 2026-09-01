#!/usr/bin/env python3
"""Bounded FRED/ALFRED API adapter with protected local credentials."""

from __future__ import annotations

import datetime as dt
import json
import os
import socket
import stat
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable, Mapping

import runtime_paths

BASE_URL = "https://api.stlouisfed.org/fred"
API_KEY_ENV = "FRED_API_KEY"
MAX_API_KEY_BYTES = 4096
MAX_RESPONSE_BYTES = 10 * 1024 * 1024
REQUEST_TIMEOUT_SECONDS = 30
MAX_ATTEMPTS = 3
RETRY_DELAYS = (0.5, 1.0)


class FredAdapterError(RuntimeError):
    def __init__(
        self,
        kind: str,
        message: str,
        *,
        code: int | str | None = None,
        retryable: bool = False,
        retry_after: float | None = None,
    ) -> None:
        super().__init__(message)
        self.kind = kind
        self.code = code
        self.retryable = retryable
        self.retry_after = retry_after


@dataclass(frozen=True)
class FredCredential:
    api_key: str
    source: str
    capture_label: str


@dataclass(frozen=True)
class FredResult:
    operation: str
    path: str
    parameters: dict[str, Any]
    data: dict[str, Any]
    raw_response: bytes
    fetched_at: str


class SameHostRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Reject redirects that could disclose the query-string API key."""

    def redirect_request(self, req: Any, fp: Any, code: int, msg: str, headers: Any, newurl: str) -> Any:
        old_host = urllib.parse.urlsplit(req.full_url).netloc.lower()
        new_host = urllib.parse.urlsplit(newurl).netloc.lower()
        if old_host != new_host:
            raise urllib.error.HTTPError(newurl, code, "cross-host redirect rejected", headers, fp)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z")


def api_key_path(
    home: Path | None = None,
    environment: Mapping[str, str] | None = None,
) -> Path:
    try:
        return runtime_paths.config_file("fred-api-key", environment, home=home)
    except runtime_paths.RuntimePathError as exc:
        raise FredAdapterError("invalid_configuration", str(exc)) from exc


def _sanitize(message: Any, secrets: tuple[str, ...] = ()) -> str:
    cleaned = str(message).replace("\r", " ").replace("\n", " ")[:500]
    for secret in secrets:
        if secret:
            cleaned = cleaned.replace(secret, "[REDACTED]")
    return cleaned


def _validate_key(value: str) -> str:
    normalized = value.strip()
    if len(normalized) != 32 or not normalized.isascii() or not normalized.isalnum() or normalized != normalized.lower():
        raise FredAdapterError(
            "invalid_configuration",
            "FRED API key must be a 32-character lowercase alphanumeric string",
        )
    return normalized


def load_credential(
    environment: Mapping[str, str] | None = None,
    *,
    home: Path | None = None,
) -> FredCredential:
    environ = os.environ if environment is None else environment
    environment_value = environ.get(API_KEY_ENV, "").strip()
    if environment_value:
        return FredCredential(
            api_key=_validate_key(environment_value),
            source="environment",
            capture_label=f"environment:{API_KEY_ENV}",
        )

    path = api_key_path(home, environ)
    path_display = runtime_paths.display_path(path, home=home)
    try:
        metadata = path.lstat()
    except FileNotFoundError as exc:
        raise FredAdapterError(
            "missing_configuration",
            f"configure {API_KEY_ENV} or {path_display}",
        ) from exc
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise FredAdapterError(
            "invalid_configuration",
            f"{path_display} must be a regular file, not a symlink",
        )
    if hasattr(os, "getuid") and metadata.st_uid != os.getuid():
        raise FredAdapterError(
            "invalid_configuration",
            f"{path_display} must be owned by the current user",
        )
    if stat.S_IMODE(metadata.st_mode) & 0o077:
        raise FredAdapterError(
            "invalid_configuration",
            f"{path_display} permissions must be 0600 or stricter",
        )
    if metadata.st_size < 1 or metadata.st_size > MAX_API_KEY_BYTES:
        raise FredAdapterError(
            "invalid_configuration",
            f"{path_display} has an invalid size",
        )
    try:
        value = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise FredAdapterError(
            "invalid_configuration",
            f"cannot read {path_display}: {_sanitize(exc)}",
        ) from exc
    if "\n" in value.rstrip("\n") or "\r" in value:
        raise FredAdapterError(
            "invalid_configuration",
            f"{path_display} must contain exactly one non-empty line",
        )
    return FredCredential(
        api_key=_validate_key(value),
        source="secure-file",
        capture_label=f"secure-file:{path_display}",
    )


def _bounded_retry_after(headers: Mapping[str, str] | None) -> float | None:
    if headers is None:
        return None
    value = headers.get("Retry-After")
    if value is None:
        return None
    try:
        seconds = float(value)
    except ValueError:
        return None
    return max(0.0, min(seconds, 10.0))


def _parse_json(raw: bytes, *, secret: str) -> dict[str, Any]:
    try:
        payload = json.loads(
            raw.decode("utf-8"),
            parse_float=Decimal,
            parse_constant=lambda value: (_ for _ in ()).throw(ValueError(f"invalid constant: {value}")),
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise FredAdapterError(
            "malformed_response",
            f"FRED response is not valid UTF-8 JSON: {_sanitize(exc, (secret,))}",
        ) from exc
    if not isinstance(payload, dict):
        raise FredAdapterError("malformed_response", "FRED response must be a JSON object")
    return payload


def _validate_payload(operation: str, payload: dict[str, Any]) -> None:
    expected = {
        "search": "seriess",
        "series": "seriess",
        "observations": "observations",
        "vintages": "vintage_dates",
    }[operation]
    if not isinstance(payload.get(expected), list):
        raise FredAdapterError(
            "malformed_response",
            f"FRED {operation} response is missing the {expected} array",
        )


class FredClient:
    ENDPOINTS = {
        "search": "/series/search",
        "series": "/series",
        "observations": "/series/observations",
        "vintages": "/series/vintagedates",
    }

    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = BASE_URL,
        user_agent: str = "money-craft",
        opener: Any | None = None,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        self._api_key = _validate_key(api_key)
        self._base_url = base_url.rstrip("/")
        self._user_agent = user_agent
        self._opener = opener or urllib.request.build_opener(SameHostRedirectHandler())
        self._sleeper = sleeper

    def request(self, operation: str, parameters: Mapping[str, Any]) -> FredResult:
        if operation not in self.ENDPOINTS:
            raise FredAdapterError("usage_error", f"unsupported FRED operation: {operation}")
        normalized = {str(key): value for key, value in parameters.items() if value is not None}
        last_error: FredAdapterError | None = None
        for attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                return self._request_once(operation, normalized)
            except FredAdapterError as exc:
                last_error = exc
                if not exc.retryable or attempt >= MAX_ATTEMPTS:
                    raise
                delay = (
                    exc.retry_after
                    if exc.retry_after is not None
                    else RETRY_DELAYS[min(attempt - 1, len(RETRY_DELAYS) - 1)]
                )
                self._sleeper(delay)
        assert last_error is not None
        raise last_error

    def _request_once(self, operation: str, parameters: dict[str, Any]) -> FredResult:
        path = self.ENDPOINTS[operation]
        wire_parameters = {**parameters, "file_type": "json", "api_key": self._api_key}
        query = urllib.parse.urlencode(
            [(key, str(value)) for key, value in wire_parameters.items()],
            safe=",",
        )
        request = urllib.request.Request(
            f"{self._base_url}{path}?{query}",
            method="GET",
            headers={"Accept": "application/json", "User-Agent": self._user_agent},
        )
        try:
            with self._opener.open(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
                content_length = response.headers.get("Content-Length")
                if content_length:
                    try:
                        declared_length = int(content_length)
                    except ValueError as exc:
                        raise FredAdapterError(
                            "malformed_response",
                            "FRED Content-Length is invalid",
                        ) from exc
                    if declared_length < 0 or declared_length > MAX_RESPONSE_BYTES:
                        raise FredAdapterError(
                            "response_too_large",
                            f"FRED response exceeds {MAX_RESPONSE_BYTES} bytes",
                        )
                raw = response.read(MAX_RESPONSE_BYTES + 1)
                if len(raw) > MAX_RESPONSE_BYTES:
                    raise FredAdapterError(
                        "response_too_large",
                        f"FRED response exceeds {MAX_RESPONSE_BYTES} bytes",
                    )
        except urllib.error.HTTPError as exc:
            retryable = exc.code == 429 or 500 <= exc.code <= 599
            body = exc.read(4096) if hasattr(exc, "read") else b""
            message = _sanitize(exc.reason, (self._api_key,))
            if body:
                try:
                    error_payload = json.loads(body.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError):
                    error_payload = None
                if isinstance(error_payload, dict) and isinstance(error_payload.get("error_message"), str):
                    message = _sanitize(error_payload["error_message"], (self._api_key,))
            raise FredAdapterError(
                "http_error",
                f"FRED HTTP {exc.code}: {message}",
                code=exc.code,
                retryable=retryable,
                retry_after=_bounded_retry_after(exc.headers),
            ) from exc
        except (urllib.error.URLError, TimeoutError, socket.timeout, OSError) as exc:
            raise FredAdapterError(
                "network_error",
                _sanitize(exc, (self._api_key,)),
                retryable=True,
            ) from exc
        payload = _parse_json(raw, secret=self._api_key)
        if isinstance(payload.get("error_code"), int):
            code = int(payload["error_code"])
            raise FredAdapterError(
                "provider_error",
                _sanitize(payload.get("error_message", "FRED provider error"), (self._api_key,)),
                code=code,
                retryable=code == 429 or 500 <= code <= 599,
            )
        _validate_payload(operation, payload)
        return FredResult(
            operation=operation,
            path=f"/fred{path}",
            parameters=parameters,
            data=payload,
            raw_response=raw,
            fetched_at=utc_now(),
        )
