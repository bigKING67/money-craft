#!/usr/bin/env python3
"""Portable global Money Craft runtime with market and macro data adapters."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import importlib.util
import json
import os
import re
import shutil
import socket
import stat
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable, Mapping
from zoneinfo import ZoneInfo

import fred_adapter
import research_run
import report_renderer
import runtime_paths
import tracking_workflow
import yfinance_adapter
from research_workflow import (
    WorkflowError,
    company_research_plan,
    prepare_thesis_update,
    thesis_diff,
    thscode_from_security_id,
    yfinance_symbol_from_security_id,
)

SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_ROOT = SCRIPT_DIR.parent
VERSION = (SKILL_ROOT / "VERSION").read_text(encoding="utf-8").strip()
BASE_URL = "https://fuyao.aicubes.cn"
API_KEY_ENV = "FUYAO_API_KEY"
MAX_API_KEY_BYTES = 4096
SHANGHAI = ZoneInfo("Asia/Shanghai")
MAX_RESPONSE_BYTES = 10 * 1024 * 1024
REQUEST_TIMEOUT_SECONDS = 30
MAX_ATTEMPTS = 3
RETRY_DELAYS = (0.5, 1.0)
THSCODE_RE = re.compile(r"^\d{6}\.(?:SH|SZ|BJ)$")
YFINANCE_SYMBOL_RE = re.compile(r"^[A-Z0-9][A-Z0-9.-]{0,31}$")
FRED_SERIES_ID_RE = re.compile(r"^[A-Z0-9][A-Z0-9._-]{0,127}$")
SOURCE_ID_RE = re.compile(r"^S\d{2,4}$")
REPORT_RE = re.compile(r"^(?:19|20)\d{2}-[1-4]$")
DATA_PYTHON_ENV = "MONEY_CRAFT_DATA_PYTHON"
DATA_RUNTIME_GUARD = "MONEY_CRAFT_DATA_RUNTIME_ACTIVE"
TRANSIENT_BUSINESS_CODES = {4001, 5002, 5003}
AUTH_CODES = {2001, 2003}

EXIT_USAGE = 2
EXIT_CONFIG = 3
EXIT_PROVIDER = 4
EXIT_TRANSIENT = 5
EXIT_SCHEMA = 6


class MoneyCraftError(RuntimeError):
    def __init__(
        self,
        kind: str,
        message: str,
        *,
        code: int | str | None = None,
        retryable: bool = False,
        exit_code: int = EXIT_PROVIDER,
        request_id: str | None = None,
        retry_after: float | None = None,
    ) -> None:
        super().__init__(message)
        self.kind = kind
        self.code = code
        self.retryable = retryable
        self.exit_code = exit_code
        self.request_id = request_id
        self.retry_after = retry_after


@dataclass(frozen=True)
class ProviderResult:
    operation: str
    path: str
    parameters: dict[str, Any]
    payload: dict[str, Any]
    raw_response: bytes
    fetched_at: str
    provider: str = "fuyao"


@dataclass(frozen=True)
class FuyaoCredential:
    api_key: str
    source: str
    capture_label: str


class SameHostRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Do not forward the API key to a different redirect host."""

    def redirect_request(self, req: Any, fp: Any, code: int, msg: str, headers: Any, newurl: str) -> Any:
        old_host = urllib.parse.urlsplit(req.full_url).netloc.lower()
        new_host = urllib.parse.urlsplit(newurl).netloc.lower()
        if old_host != new_host:
            raise urllib.error.HTTPError(newurl, code, "cross-host redirect rejected", headers, fp)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z")


def jsonable(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, dict):
        return {str(key): jsonable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [jsonable(item) for item in value]
    if isinstance(value, tuple):
        return [jsonable(item) for item in value]
    return value


def print_json(payload: Any) -> None:
    print(json.dumps(jsonable(payload), ensure_ascii=False, indent=2, sort_keys=False))


def sanitize_message(message: Any, secrets: tuple[str, ...] = ()) -> str:
    cleaned = str(message).replace("\r", " ").replace("\n", " ")[:500]
    for secret in secrets:
        if secret:
            cleaned = cleaned.replace(secret, "[REDACTED]")
    return cleaned


def fuyao_api_key_path(
    home: Path | None = None,
    environment: Mapping[str, str] | None = None,
) -> Path:
    try:
        return runtime_paths.config_file("fuyao-api-key", environment, home=home)
    except runtime_paths.RuntimePathError as exc:
        raise MoneyCraftError(
            "invalid_configuration",
            sanitize_message(exc),
            exit_code=EXIT_CONFIG,
        ) from exc


def load_fuyao_credential(
    environment: Mapping[str, str] | None = None,
    *,
    home: Path | None = None,
) -> FuyaoCredential:
    environ = os.environ if environment is None else environment
    environment_value = environ.get(API_KEY_ENV, "").strip()
    if environment_value:
        return FuyaoCredential(
            api_key=environment_value,
            source="environment",
            capture_label=f"environment:{API_KEY_ENV}",
        )

    path = fuyao_api_key_path(home, environ)
    path_display = runtime_paths.display_path(path, home=home)
    try:
        metadata = path.lstat()
    except FileNotFoundError as exc:
        raise MoneyCraftError(
            "missing_configuration",
            f"configure {API_KEY_ENV} or {path_display}",
            exit_code=EXIT_CONFIG,
        ) from exc
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise MoneyCraftError(
            "invalid_configuration",
            f"{path_display} must be a regular file, not a symlink",
            exit_code=EXIT_CONFIG,
        )
    if hasattr(os, "getuid") and metadata.st_uid != os.getuid():
        raise MoneyCraftError(
            "invalid_configuration",
            f"{path_display} must be owned by the current user",
            exit_code=EXIT_CONFIG,
        )
    if stat.S_IMODE(metadata.st_mode) & 0o077:
        raise MoneyCraftError(
            "invalid_configuration",
            f"{path_display} permissions must be 0600 or stricter",
            exit_code=EXIT_CONFIG,
        )
    if metadata.st_size < 1 or metadata.st_size > MAX_API_KEY_BYTES:
        raise MoneyCraftError(
            "invalid_configuration",
            f"{path_display} has an invalid size",
            exit_code=EXIT_CONFIG,
        )
    try:
        value = path.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeDecodeError) as exc:
        raise MoneyCraftError(
            "invalid_configuration",
            f"cannot read {path_display}: {sanitize_message(exc)}",
            exit_code=EXIT_CONFIG,
        ) from exc
    if not value or "\n" in value or "\r" in value:
        raise MoneyCraftError(
            "invalid_configuration",
            f"{path_display} must contain exactly one non-empty line",
            exit_code=EXIT_CONFIG,
        )
    return FuyaoCredential(
        api_key=value,
        source="secure-file",
        capture_label=f"secure-file:{path_display}",
    )


def parse_json(raw: bytes) -> dict[str, Any]:
    try:
        text = raw.decode("utf-8")
        payload = json.loads(
            text,
            parse_float=Decimal,
            parse_constant=lambda value: (_ for _ in ()).throw(ValueError(f"invalid constant: {value}")),
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise MoneyCraftError(
            "malformed_response",
            f"provider response is not valid UTF-8 JSON: {exc}",
            exit_code=EXIT_SCHEMA,
        ) from exc
    if not isinstance(payload, dict):
        raise MoneyCraftError(
            "malformed_response",
            "provider response must be a JSON object",
            exit_code=EXIT_SCHEMA,
        )
    if not isinstance(payload.get("code"), int):
        raise MoneyCraftError(
            "malformed_response",
            "provider response is missing integer code",
            exit_code=EXIT_SCHEMA,
        )
    if "message" not in payload or "request_id" not in payload or "data" not in payload:
        raise MoneyCraftError(
            "malformed_response",
            "provider response does not match the ApiResponse envelope",
            exit_code=EXIT_SCHEMA,
        )
    if not isinstance(payload["message"], str) or not isinstance(payload["request_id"], str):
        raise MoneyCraftError(
            "malformed_response",
            "provider message and request_id must be strings",
            exit_code=EXIT_SCHEMA,
        )
    if payload["data"] is not None and not isinstance(payload["data"], dict):
        raise MoneyCraftError(
            "malformed_response",
            "provider data must be an object or null",
            exit_code=EXIT_SCHEMA,
        )
    return payload


def bounded_retry_after(headers: Mapping[str, str] | None) -> float | None:
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


class FuyaoClient:
    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = BASE_URL,
        opener: Any | None = None,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        if not api_key.strip():
            raise MoneyCraftError(
                "missing_configuration",
                f"{API_KEY_ENV} is not configured",
                exit_code=EXIT_CONFIG,
            )
        self._api_key = api_key.strip()
        self._base_url = base_url.rstrip("/")
        self._opener = opener or urllib.request.build_opener(SameHostRedirectHandler())
        self._sleeper = sleeper

    def request(self, operation: str, path: str, parameters: Mapping[str, Any]) -> ProviderResult:
        last_error: MoneyCraftError | None = None
        for attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                return self._request_once(operation, path, parameters)
            except MoneyCraftError as exc:
                last_error = exc
                if not exc.retryable:
                    raise
                if attempt >= MAX_ATTEMPTS:
                    raise MoneyCraftError(
                        exc.kind,
                        str(exc),
                        code=exc.code,
                        retryable=True,
                        exit_code=EXIT_TRANSIENT,
                        request_id=exc.request_id,
                    ) from exc
                delay = (
                    exc.retry_after
                    if exc.retry_after is not None
                    else RETRY_DELAYS[min(attempt - 1, len(RETRY_DELAYS) - 1)]
                )
                self._sleeper(delay)
        assert last_error is not None
        raise last_error

    def _request_once(self, operation: str, path: str, parameters: Mapping[str, Any]) -> ProviderResult:
        query = urllib.parse.urlencode(
            [(key, str(value)) for key, value in parameters.items() if value is not None],
            safe=",",
        )
        url = f"{self._base_url}{path}"
        if query:
            url += f"?{query}"
        request = urllib.request.Request(
            url,
            method="GET",
            headers={
                "Accept": "application/json",
                "User-Agent": f"money-craft/{VERSION}",
                "X-api-key": self._api_key,
            },
        )
        try:
            with self._opener.open(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
                content_length = response.headers.get("Content-Length")
                if content_length:
                    try:
                        declared_length = int(content_length)
                    except ValueError as exc:
                        raise MoneyCraftError(
                            "malformed_response",
                            "provider Content-Length is invalid",
                            exit_code=EXIT_SCHEMA,
                        ) from exc
                    if declared_length < 0 or declared_length > MAX_RESPONSE_BYTES:
                        raise MoneyCraftError(
                            "response_too_large",
                            f"provider response exceeds {MAX_RESPONSE_BYTES} bytes",
                            exit_code=EXIT_SCHEMA,
                        )
                raw = response.read(MAX_RESPONSE_BYTES + 1)
                if len(raw) > MAX_RESPONSE_BYTES:
                    raise MoneyCraftError(
                        "response_too_large",
                        f"provider response exceeds {MAX_RESPONSE_BYTES} bytes",
                        exit_code=EXIT_SCHEMA,
                    )
        except urllib.error.HTTPError as exc:
            retryable = exc.code == 429 or 500 <= exc.code <= 599
            message = sanitize_message(exc.reason, (self._api_key,))
            raise MoneyCraftError(
                "http_error",
                f"provider HTTP {exc.code}: {message}",
                code=exc.code,
                retryable=retryable,
                exit_code=EXIT_TRANSIENT if retryable else EXIT_PROVIDER,
                retry_after=bounded_retry_after(exc.headers),
            ) from exc
        except (urllib.error.URLError, TimeoutError, socket.timeout, OSError) as exc:
            raise MoneyCraftError(
                "network_error",
                sanitize_message(exc, (self._api_key,)),
                retryable=True,
                exit_code=EXIT_TRANSIENT,
            ) from exc
        payload = parse_json(raw)
        code = payload["code"]
        request_id = payload.get("request_id") if isinstance(payload.get("request_id"), str) else None
        if code != 0:
            retryable = code in TRANSIENT_BUSINESS_CODES
            if code in AUTH_CODES:
                kind = "authentication_error"
            elif 1000 <= code < 2000:
                kind = "validation_error"
            elif 3000 <= code < 4000:
                kind = "data_error"
            elif retryable:
                kind = "transient_provider_error"
            else:
                kind = "provider_error"
            raise MoneyCraftError(
                kind,
                sanitize_message(payload.get("message", "provider business error"), (self._api_key,)),
                code=code,
                retryable=retryable,
                exit_code=EXIT_TRANSIENT if retryable else EXIT_PROVIDER,
                request_id=request_id,
            )
        return ProviderResult(
            operation=operation,
            path=path,
            parameters={key: value for key, value in parameters.items() if value is not None},
            payload=payload,
            raw_response=raw,
            fetched_at=utc_now(),
        )


def parse_iso_date(value: str) -> dt.date:
    try:
        return dt.date.fromisoformat(value)
    except ValueError as exc:
        raise MoneyCraftError(
            "usage_error",
            f"invalid date {value!r}; expected YYYY-MM-DD",
            exit_code=EXIT_USAGE,
        ) from exc


def date_to_ms(value: str) -> int:
    parsed = parse_iso_date(value)
    moment = dt.datetime.combine(parsed, dt.time.min, tzinfo=SHANGHAI)
    return int(moment.timestamp() * 1000)


def add_years(value: dt.date, years: int) -> dt.date:
    try:
        return value.replace(year=value.year + years)
    except ValueError:
        return value.replace(month=2, day=28, year=value.year + years)


def validate_range(start: str, end: str, *, max_years: int | None = None) -> None:
    start_date = parse_iso_date(start)
    end_date = parse_iso_date(end)
    if end_date < start_date:
        raise MoneyCraftError("usage_error", "end date precedes start date", exit_code=EXIT_USAGE)
    if max_years is not None and end_date > add_years(start_date, max_years):
        raise MoneyCraftError(
            "usage_error",
            f"date range exceeds {max_years} years",
            exit_code=EXIT_USAGE,
        )


def parse_thscodes(value: str | None, *, maximum: int = 100) -> list[str]:
    if not isinstance(value, str):
        raise MoneyCraftError("usage_error", "a complete Fuyao thscode is required", exit_code=EXIT_USAGE)
    raw_items = [item.strip().upper() for item in value.split(",")]
    if not raw_items or any(not item for item in raw_items):
        raise MoneyCraftError("usage_error", "thscodes must not be empty", exit_code=EXIT_USAGE)
    result: list[str] = []
    seen: set[str] = set()
    for item in raw_items:
        if not THSCODE_RE.fullmatch(item):
            raise MoneyCraftError(
                "usage_error",
                f"invalid A-share thscode: {item}",
                exit_code=EXIT_USAGE,
            )
        if item not in seen:
            seen.add(item)
            result.append(item)
    if len(result) > maximum:
        raise MoneyCraftError(
            "usage_error",
            f"too many thscodes; maximum is {maximum}",
            exit_code=EXIT_USAGE,
        )
    return result


def parse_yfinance_symbol(value: str | None) -> str:
    symbol = value.strip().upper() if isinstance(value, str) else ""
    if not YFINANCE_SYMBOL_RE.fullmatch(symbol):
        raise MoneyCraftError(
            "usage_error",
            "yfinance symbol must be an explicit Yahoo Finance equity symbol such as NVDA or 0700.HK",
            exit_code=EXIT_USAGE,
        )
    return symbol


def parse_fred_series_id(value: str | None) -> str:
    series_id = value.strip().upper() if isinstance(value, str) else ""
    if not FRED_SERIES_ID_RE.fullmatch(series_id):
        raise MoneyCraftError(
            "usage_error",
            "FRED series id must be an explicit identifier such as FEDFUNDS or T10YIE",
            exit_code=EXIT_USAGE,
        )
    return series_id


def preferred_data_python(
    environment: Mapping[str, str] | None = None,
    *,
    home: Path | None = None,
) -> tuple[Path, str]:
    try:
        return runtime_paths.preferred_runtime_python("data", environment, home=home)
    except runtime_paths.RuntimePathError as exc:
        raise MoneyCraftError(
            "invalid_configuration",
            sanitize_message(exc),
            exit_code=EXIT_CONFIG,
        ) from exc


def preferred_report_python(
    environment: Mapping[str, str] | None = None,
    *,
    home: Path | None = None,
) -> tuple[Path, str]:
    try:
        return runtime_paths.preferred_runtime_python("report", environment, home=home)
    except runtime_paths.RuntimePathError as exc:
        raise MoneyCraftError(
            "invalid_configuration",
            sanitize_message(exc),
            exit_code=EXIT_CONFIG,
        ) from exc


def probe_python_modules(
    python: Path,
    modules: tuple[tuple[str, str], ...],
    *,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> tuple[dict[str, bool], str | None]:
    """Inspect optional modules in the interpreter that will actually use them."""

    unavailable = {name: False for name, _module in modules}
    if not python.is_file() or not os.access(python, os.X_OK):
        return unavailable, None
    if Path(sys.executable).absolute() == python.absolute():
        return {
            name: importlib.util.find_spec(module) is not None
            for name, module in modules
        }, None

    probe = (
        "import importlib.util,json,sys;"
        "print(json.dumps({name: importlib.util.find_spec(module) is not None "
        "for name, module in zip(sys.argv[1::2], sys.argv[2::2])}))"
    )
    arguments = [item for pair in modules for item in pair]
    try:
        completed = runner(
            [str(python), "-c", probe, *arguments],
            text=True,
            capture_output=True,
            check=False,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return unavailable, f"preferred runtime dependency probe failed: {type(exc).__name__}"
    if completed.returncode != 0:
        return unavailable, f"preferred runtime dependency probe exited {completed.returncode}"
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError:
        return unavailable, "preferred runtime dependency probe returned invalid JSON"
    if not isinstance(payload, dict) or set(payload) != set(unavailable) or any(
        not isinstance(value, bool) for value in payload.values()
    ):
        return unavailable, "preferred runtime dependency probe returned an invalid contract"
    return {name: payload[name] for name in unavailable}, None


def maybe_reexec_data_runtime() -> None:
    if os.environ.get(DATA_RUNTIME_GUARD) == "1":
        return
    candidate, source = preferred_data_python()
    if not source.startswith("environment:") and sys.prefix != sys.base_prefix:
        return
    if not candidate.is_file() or not os.access(candidate, os.X_OK):
        return
    try:
        if Path(sys.prefix).resolve() == candidate.parent.parent.resolve():
            return
    except OSError:
        pass
    environment = dict(os.environ)
    environment[DATA_RUNTIME_GUARD] = "1"
    environment["MONEY_CRAFT_DATA_RUNTIME_SOURCE"] = source
    os.execve(
        str(candidate),
        [str(candidate), str(Path(__file__).resolve()), *sys.argv[1:]],
        environment,
    )


def validate_capture_args(capture_dir: str | None, source_id: str | None) -> tuple[Path, str] | None:
    if bool(capture_dir) != bool(source_id):
        raise MoneyCraftError(
            "usage_error",
            "--capture-dir and --source-id must be provided together",
            exit_code=EXIT_USAGE,
        )
    if capture_dir is None or source_id is None:
        return None
    if not SOURCE_ID_RE.fullmatch(source_id):
        raise MoneyCraftError(
            "usage_error",
            "source id must match S01",
            exit_code=EXIT_USAGE,
        )
    return Path(capture_dir).expanduser().resolve(), source_id


def atomic_write(path: Path, data: bytes) -> None:
    with path.open("xb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())


def capture_result(
    root: Path,
    source_id: str,
    result: ProviderResult,
    *,
    output_parameters: Mapping[str, Any],
    authentication: str = f"environment:{API_KEY_ENV}",
    forbidden_values: tuple[str, ...] = (),
) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    if root.is_symlink() or not root.is_dir():
        raise MoneyCraftError("capture_error", "capture root must be a real directory")
    destination = root / source_id
    if destination.exists() or destination.is_symlink():
        raise MoneyCraftError("capture_error", f"capture already exists: {source_id}")
    staging = root / f".{source_id}.staging.{uuid.uuid4().hex}"
    staging.mkdir(mode=0o700)
    try:
        for value in forbidden_values:
            if value and value.encode("utf-8") in result.raw_response:
                raise MoneyCraftError(
                    "capture_error",
                    "provider response contains authentication material; capture rejected",
                )
        request_payload = {
            "schema": "money-craft.sanitized-request.v1",
            "provider": result.provider,
            "operation": result.operation,
            "method": "GET",
            "path": result.path,
            "parameters": jsonable(output_parameters),
            "authentication": authentication,
        }
        request_bytes = (json.dumps(request_payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
        response_hash = hashlib.sha256(result.raw_response).hexdigest()
        manifest = {
            "schema": "money-craft.source-capture.v1",
            "source_id": source_id,
            "provider": result.provider,
            "operation": result.operation,
            "fetched_at": result.fetched_at,
            "request_id": result.payload.get("request_id"),
            "response_sha256": response_hash,
            "response_bytes": len(result.raw_response),
            "files": ["request.json", "response.json", "capture.json"],
        }
        manifest_bytes = (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
        atomic_write(staging / "request.json", request_bytes)
        atomic_write(staging / "response.json", result.raw_response)
        atomic_write(staging / "capture.json", manifest_bytes)
        os.replace(staging, destination)
    except Exception:
        if staging.exists():
            shutil.rmtree(staging)
        raise
    return destination


def filter_calendar(data: dict[str, Any] | None, start: str | None, end: str | None) -> dict[str, Any] | None:
    if data is None or (start is None and end is None):
        return data
    filtered = dict(data)
    items = data.get("item")
    if not isinstance(items, list):
        raise MoneyCraftError("malformed_response", "calendar data.item must be an array", exit_code=EXIT_SCHEMA)
    start_key = parse_iso_date(start).strftime("%Y%m%d") if start else None
    end_key = parse_iso_date(end).strftime("%Y%m%d") if end else None
    result_items = []
    for item in items:
        if not isinstance(item, dict) or not isinstance(item.get("date"), str):
            raise MoneyCraftError("malformed_response", "calendar item is invalid", exit_code=EXIT_SCHEMA)
        key = item["date"]
        if start_key and key < start_key:
            continue
        if end_key and key > end_key:
            continue
        result_items.append(item)
    filtered["item"] = result_items
    return filtered


def add_capture_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--capture-dir")
    parser.add_argument("--source-id")


def add_provider_option(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--provider", choices=["fuyao", "yfinance", "fred"], default="fuyao")


def add_fred_provider_option(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--provider", choices=["fred"], default="fred")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    doctor = subparsers.add_parser("doctor")
    doctor.add_argument("--json", action="store_true")
    self_test = subparsers.add_parser("self-test")
    self_test.add_argument("--json", action="store_true")

    data = subparsers.add_parser("data")
    data_subparsers = data.add_subparsers(dest="data_command", required=True)
    search = data_subparsers.add_parser("search")
    add_provider_option(search)
    search.add_argument("--query", required=True)
    search.add_argument("--limit", type=int, default=10)
    add_capture_options(search)
    snapshot = data_subparsers.add_parser("snapshot")
    add_provider_option(snapshot)
    snapshot.add_argument("--thscodes")
    snapshot.add_argument("--symbol")
    add_capture_options(snapshot)
    history = data_subparsers.add_parser("history")
    add_provider_option(history)
    history.add_argument("--thscode")
    history.add_argument("--symbol")
    history.add_argument("--start", required=True)
    history.add_argument("--end", required=True)
    history.add_argument("--interval", choices=["1d"], default="1d")
    history.add_argument("--adjust", choices=["none", "forward", "backward", "auto"], default="forward")
    add_capture_options(history)
    valuations = data_subparsers.add_parser("valuations")
    add_provider_option(valuations)
    valuations.add_argument("--thscodes")
    valuations.add_argument("--symbol")
    add_capture_options(valuations)
    financials = data_subparsers.add_parser("financials")
    add_provider_option(financials)
    financials.add_argument("--thscode")
    financials.add_argument("--symbol")
    financials.add_argument("--statement", choices=["income", "balance", "cash-flow"], required=True)
    financials.add_argument("--period", choices=["annual", "quarterly"], default="annual")
    financials.add_argument("--limit", type=int)
    financials.add_argument("--start")
    financials.add_argument("--end")
    add_capture_options(financials)
    indicators = data_subparsers.add_parser("indicators")
    add_provider_option(indicators)
    indicators.add_argument("--thscode", required=True)
    indicators.add_argument("--report", required=True)
    add_capture_options(indicators)
    actions = data_subparsers.add_parser("corporate-actions")
    add_provider_option(actions)
    actions.add_argument("--thscode")
    actions.add_argument("--symbol")
    actions.add_argument("--start")
    actions.add_argument("--end")
    add_capture_options(actions)
    calendar = data_subparsers.add_parser("calendar")
    add_provider_option(calendar)
    calendar.add_argument("--start")
    calendar.add_argument("--end")
    add_capture_options(calendar)
    series = data_subparsers.add_parser("series")
    add_fred_provider_option(series)
    series.add_argument("--series-id", required=True)
    series.add_argument("--as-known-on")
    add_capture_options(series)
    observations = data_subparsers.add_parser("observations")
    add_fred_provider_option(observations)
    observations.add_argument("--series-id", required=True)
    observations.add_argument("--start")
    observations.add_argument("--end")
    observations.add_argument("--as-known-on")
    observations.add_argument(
        "--units",
        choices=["lin", "chg", "ch1", "pch", "pc1", "pca", "cch", "cca", "log"],
        default="lin",
    )
    observations.add_argument("--limit", type=int, default=10000)
    add_capture_options(observations)
    vintages = data_subparsers.add_parser("vintages")
    add_fred_provider_option(vintages)
    vintages.add_argument("--series-id", required=True)
    vintages.add_argument("--start")
    vintages.add_argument("--end")
    vintages.add_argument("--limit", type=int, default=1000)
    add_capture_options(vintages)

    audit = subparsers.add_parser("audit")
    audit_subparsers = audit.add_subparsers(dest="audit_command", required=True)
    for name in ("report", "financial", "reconciliation"):
        audit_parser = audit_subparsers.add_parser(name)
        audit_parser.add_argument("report_path")
        audit_parser.add_argument("--json", action="store_true")

    research = subparsers.add_parser("research")
    research_subparsers = research.add_subparsers(dest="research_command", required=True)
    for name in ("plan", "init"):
        research_command = research_subparsers.add_parser(name)
        research_command.add_argument("--security", required=True)
        research_command.add_argument("--security-id")
        research_command.add_argument("--thscode")
        research_command.add_argument("--base-currency")
        research_command.add_argument("--as-of", required=True)
        research_command.add_argument("--latest-report", required=True)
        research_command.add_argument("--latest-report-end")
        research_command.add_argument("--latest-annual-report")
        research_command.add_argument(
            "--provider-mode", choices=["auto", "required", "disabled"], default="auto"
        )
        research_command.add_argument(
            "--provider", choices=["auto", "fuyao", "yfinance"], default="auto"
        )
        if name == "init":
            location = research_command.add_mutually_exclusive_group()
            location.add_argument("--workspace", type=Path)
            location.add_argument("--output-root", type=Path)
        research_command.add_argument("--json", action="store_true")
    research_collect = research_subparsers.add_parser("collect")
    research_collect.add_argument("--workspace", required=True, type=Path)
    research_collect.add_argument("--resume", action="store_true")
    research_collect.add_argument("--json", action="store_true")
    research_import = research_subparsers.add_parser("import-official")
    research_import.add_argument("--workspace", required=True, type=Path)
    research_import.add_argument("--source-id", required=True)
    research_import.add_argument("--file", required=True, type=Path)
    research_import.add_argument("--url", required=True)
    research_import.add_argument("--title")
    research_import.add_argument("--retrieved-on")
    research_import.add_argument("--json", action="store_true")
    for name in ("status", "finalize"):
        research_command = research_subparsers.add_parser(name)
        research_command.add_argument("--workspace", required=True, type=Path)
        research_command.add_argument("--json", action="store_true")

    thesis = subparsers.add_parser("thesis")
    thesis_subparsers = thesis.add_subparsers(dest="thesis_command", required=True)
    prepare_update = thesis_subparsers.add_parser("prepare-update")
    prepare_update.add_argument("--previous", required=True, type=Path)
    prepare_update.add_argument("--as-of", required=True)
    prepare_update.add_argument("--json", action="store_true")
    diff = thesis_subparsers.add_parser("diff")
    diff.add_argument("--previous", required=True, type=Path)
    diff.add_argument("--current", required=True, type=Path)
    diff.add_argument("--json", action="store_true")

    track = subparsers.add_parser("track")
    track_subparsers = track.add_subparsers(dest="track_command", required=True)
    track_init = track_subparsers.add_parser("init")
    track_init.add_argument("--tracking-root", required=True, type=Path)
    track_init.add_argument("--as-of", required=True)
    track_init.add_argument("--previous", type=Path)
    track_init.add_argument("--source-revision", type=Path)
    track_init.add_argument("--workspace", type=Path)
    track_init.add_argument("--json", action="store_true")
    track_check = track_subparsers.add_parser("check")
    track_check.add_argument("--workspace", required=True, type=Path)
    track_check.add_argument("--json", action="store_true")
    track_status = track_subparsers.add_parser("status")
    track_status.add_argument("--tracking-root", required=True, type=Path)
    track_status.add_argument("--json", action="store_true")
    track_verify = track_subparsers.add_parser("verify")
    track_verify.add_argument("--tracking-root", required=True, type=Path)
    track_verify.add_argument("--no-require-read-only", action="store_true")
    track_verify.add_argument("--json", action="store_true")

    report = subparsers.add_parser("report")
    report_subparsers = report.add_subparsers(dest="report_command", required=True)
    report_render = report_subparsers.add_parser("render")
    report_render.add_argument("--source", required=True, type=Path)
    report_render.add_argument("--output-dir", type=Path)
    report_render.add_argument("--output-html", type=Path)
    report_render.add_argument("--output-pdf", type=Path)
    report_render.add_argument("--html-only", action="store_true")
    report_render.add_argument("--theme", default=report_renderer.CANONICAL_THEME)
    report_render.add_argument("--evidence-manifest", type=Path)
    report_render.add_argument("--audit", type=Path)
    report_render.add_argument("--revision-manifest", type=Path)
    report_render.add_argument("--archive-manifest", type=Path)
    report_render.add_argument("--no-charts", action="store_true")
    report_render.add_argument("--json", action="store_true")
    report_verify = report_subparsers.add_parser("verify")
    report_verify.add_argument("--source", required=True, type=Path)
    report_verify.add_argument("--html", required=True, type=Path)
    report_verify.add_argument("--pdf", type=Path)
    report_verify.add_argument("--json", action="store_true")
    return parser


def doctor_payload() -> dict[str, Any]:
    credential: FuyaoCredential | None = None
    credential_error: MoneyCraftError | None = None
    try:
        credential = load_fuyao_credential()
    except MoneyCraftError as exc:
        credential_error = exc
    fred_credential: fred_adapter.FredCredential | None = None
    fred_credential_error: fred_adapter.FredAdapterError | None = None
    try:
        fred_credential = fred_adapter.load_credential()
    except fred_adapter.FredAdapterError as exc:
        fred_credential_error = exc
    data_python, data_python_source = preferred_data_python()
    report_python, report_python_source = preferred_report_python()
    report_dependencies, report_dependency_probe_error = probe_python_modules(
        report_python,
        (
            ("markdown", "markdown"),
            ("weasyprint", "weasyprint"),
            ("pypdf", "pypdf"),
        ),
    )
    try:
        config_root, config_root_source = runtime_paths.config_home()
        data_root, data_root_source = runtime_paths.data_home()
        cache_root, cache_root_source = runtime_paths.cache_home()
    except runtime_paths.RuntimePathError as exc:
        raise MoneyCraftError(
            "invalid_configuration",
            sanitize_message(exc),
            exit_code=EXIT_CONFIG,
        ) from exc
    research_output_error: research_run.ResearchRunError | None = None
    try:
        research_output_root, research_output_source = research_run.output_root()
    except research_run.ResearchRunError as exc:
        research_output_error = exc
        research_output_root = None
        research_output_source = None
    return {
        "schema": "money-craft.doctor.v1",
        "version": VERSION,
        "python": {
            "version": ".".join(str(value) for value in sys.version_info[:3]),
            "supported": sys.version_info >= (3, 10),
        },
        "runtime": {
            "skill_root": str(SKILL_ROOT),
            "canonical_files_present": all(
                (SKILL_ROOT / path).is_file()
                for path in (
                    "SKILL.md",
                    "VERSION",
                    "scripts/money_craft.py",
                    "scripts/fred_adapter.py",
                    "scripts/runtime_paths.py",
                    "scripts/yfinance_adapter.py",
                    "requirements-yfinance.txt",
                    "scripts/report_renderer.py",
                    "reporting/report.html",
                    "reporting/report.css",
                    "reporting/report.js",
                )
            ),
        },
        "data_runtime": {
            "preferred_python": str(data_python),
            "configuration_source": data_python_source,
            "available": data_python.is_file() and os.access(data_python, os.X_OK),
            "active": sys.prefix != sys.base_prefix and Path(sys.prefix) == data_python.parent.parent,
            "environment_variable": DATA_PYTHON_ENV,
            "network_checked": False,
        },
        "runtime_paths": {
            "config_home": str(config_root),
            "config_home_source": config_root_source,
            "data_home": str(data_root),
            "data_home_source": data_root_source,
            "cache_home": str(cache_root),
            "cache_home_source": cache_root_source,
            "explicit_env_file": os.environ.get(runtime_paths.ENV_FILE_ACTIVE_ENV),
            "environment_variables": {
                "config_home": runtime_paths.CONFIG_HOME_ENV,
                "data_home": runtime_paths.DATA_HOME_ENV,
                "cache_home": runtime_paths.CACHE_HOME_ENV,
                "env_file": runtime_paths.ENV_FILE_ENV,
            },
        },
        "report_renderer": {
            "theme": report_renderer.CANONICAL_THEME,
            "layout_mode": report_renderer.LAYOUT_MODE,
            "preferred_python": str(report_python),
            "configuration_source": report_python_source,
            "available": report_python.is_file() and os.access(report_python, os.X_OK),
            "environment_variable": runtime_paths.REPORT_PYTHON_ENV,
            "assets_present": all(
                path.is_file()
                for path in (
                    report_renderer.DEFAULT_TEMPLATE,
                    report_renderer.DEFAULT_STYLE,
                    report_renderer.DEFAULT_SCRIPT,
                )
            ),
            "optional_dependencies": report_dependencies,
            "dependency_probe_error": report_dependency_probe_error,
            "network_checked": False,
        },
        "fuyao": {
            "configured": credential is not None,
            "configuration_source": credential.source if credential else None,
            "environment_variable": API_KEY_ENV,
            "secure_file": runtime_paths.display_path(fuyao_api_key_path()),
            "configuration_error": (
                {
                    "kind": credential_error.kind,
                    "message": sanitize_message(credential_error),
                }
                if credential_error and credential_error.kind != "missing_configuration"
                else None
            ),
            "network_checked": False,
        },
        "yfinance": {
            "configured": importlib.util.find_spec("yfinance") is not None,
            "version": yfinance_adapter.installed_version(),
            "requirements": "skills/money-craft/requirements-yfinance.txt",
            "adapter_scope": "Hong Kong and U.S. secondary market data",
            "official_filings_remain_primary": True,
            "network_checked": False,
        },
        "fred": {
            "configured": fred_credential is not None,
            "configuration_source": fred_credential.source if fred_credential else None,
            "environment_variable": fred_adapter.API_KEY_ENV,
            "secure_file": runtime_paths.display_path(fred_adapter.api_key_path()),
            "configuration_error": (
                {
                    "kind": fred_credential_error.kind,
                    "message": sanitize_message(fred_credential_error),
                }
                if fred_credential_error and fred_credential_error.kind != "missing_configuration"
                else None
            ),
            "adapter_scope": "FRED and ALFRED economic time series and vintages",
            "network_checked": False,
        },
        "research_output": {
            "root": str(research_output_root) if research_output_root else None,
            "configuration_source": research_output_source,
            "environment_variable": research_run.OUTPUT_ROOT_ENV,
            "exists": research_output_root.is_dir() if research_output_root else False,
            "valid": research_output_error is None,
            "configuration_error": (
                {
                    "kind": research_output_error.kind,
                    "message": sanitize_message(research_output_error),
                }
                if research_output_error
                else None
            ),
            "network_checked": False,
        },
    }


def self_test_payload() -> dict[str, Any]:
    checks: list[str] = []
    errors: list[str] = []
    try:
        if parse_thscodes("600519.sh,000001.SZ") != ["600519.SH", "000001.SZ"]:
            raise AssertionError("thscode normalization failed")
        checks.append("thscode-validation")
        if date_to_ms("2026-01-01") != 1767196800000:
            raise AssertionError("Asia/Shanghai date conversion failed")
        checks.append("shanghai-date-conversion")
        from financial_rigor import audit_text as audit_financial
        from report_audit import audit_text as audit_report

        sample = """---
schema: money-craft.report.v1
workflow: research
security: Example
thscode: 600519.SH
as_of: 2026-08-23
data_cutoff: 2026-08-23T12:00:00+08:00
base_currency: CNY
provider_status: unavailable
---
# Example
## 结论
Evidence-limited example.
## 事实与证据
- 收入以正式报告为准 [S01]
- 现金流由独立来源复核 [S02]
## 估值与假设
Scenario only.
<!-- money-craft-calc: {"id":"C01","operation":"multiply","inputs":["2","3"],"expected":"6"} -->
## 风险与反方证据
Evidence may change.
## 证伪条件
Official facts change.
## 来源索引
- [S01] https://example.invalid/official
- [S02] `captures/S02/capture.json`
"""
        if not audit_report(sample)["valid"]:
            raise AssertionError("report audit fixture failed")
        checks.append("report-audit")
        if not audit_financial(sample)["valid"]:
            raise AssertionError("financial audit fixture failed")
        checks.append("financial-audit")
        plan = company_research_plan(
            security="Example",
            thscode="600519.SH",
            as_of="2026-08-23",
            latest_report="2026-2",
            provider={"mode": "auto", "configured": True, "network_checked": False},
            today=dt.date(2026, 8, 23),
        )
        if plan["latest_annual_period"] != "2025-4" or len(plan["provider_operations"]) != 14:
            raise AssertionError("company research plan fixture failed")
        checks.append("company-research-plan")
        case = research_run.derived_case(plan, "0" * 64)
        if len(case["operations"]) != 14 or [item["id"] for item in case["official_sources"]] != [
            "S11",
            "S12",
            "S13",
            "S18",
            "S19",
            "S20",
        ]:
            raise AssertionError("research run case derivation failed")
        checks.append("research-run-case")
        global_plan = company_research_plan(
            security="Global Example",
            security_id="US-NASDAQ:EXAMPLE",
            base_currency="USD",
            as_of="2026-08-23",
            latest_report="2026-2",
            latest_report_end="2026-06-30",
            latest_annual_report="2025-4",
            provider={"mode": "auto", "configured": False, "network_checked": False},
            today=dt.date(2026, 8, 23),
        )
        if (
            global_plan["identity"]["security_id"] != "US-NASDAQ:EXAMPLE"
            or global_plan["identity"]["base_currency"] != "USD"
            or global_plan["provider_operations"]
            or global_plan["provider"]["availability"] != "not-configured"
        ):
            raise AssertionError("global security research plan fixture failed")
        checks.append("global-security-research-plan")
        health = tracking_workflow.health_contract(
            {
                "hypotheses": [
                    {"ID": "H01", "状态": "WEAKENED"},
                    {"ID": "H02", "状态": "WEAKENED"},
                    {"ID": "H03", "状态": "WEAKENED"},
                ],
                "red_lines": [{"ID": "R01", "当前状态": "WATCH"}],
            }
        )
        if health["score"] != 7 or health["status"] != "WEAKENED":
            raise AssertionError("tracking health contract failed")
        checks.append("tracking-health-contract")
        parsed_report = report_renderer.parse_report(sample)
        if parsed_report.title != "Example":
            raise AssertionError("report renderer parser failed")
        if not all(
            path.is_file()
            for path in (
                report_renderer.DEFAULT_TEMPLATE,
                report_renderer.DEFAULT_STYLE,
                report_renderer.DEFAULT_SCRIPT,
            )
        ):
            raise AssertionError("report renderer assets are missing")
        checks.append("report-renderer-assets")
    except Exception as exc:
        errors.append(sanitize_message(exc))
    return {
        "schema": "money-craft.self-test.v1",
        "scope": "runtime",
        "version": VERSION,
        "runtime_valid": not errors,
        "network_used": False,
        "checks": checks,
        "errors": errors,
    }


def prepare_operation(args: argparse.Namespace) -> tuple[str, str, dict[str, Any], dict[str, Any]]:
    command = args.data_command
    provider = getattr(args, "provider", "fuyao")
    args.resolved_provider = provider
    output_parameters: dict[str, Any]
    fred_commands = {"search", "series", "observations", "vintages"}
    if provider == "fred" and command not in fred_commands:
        raise MoneyCraftError(
            "usage_error",
            f"FRED does not support the {command} market-data operation",
            exit_code=EXIT_USAGE,
        )
    if command in {"series", "observations", "vintages"} and provider != "fred":
        raise MoneyCraftError(
            "usage_error",
            f"{command} is a FRED-only macro-data operation",
            exit_code=EXIT_USAGE,
        )
    if command == "search":
        query = args.query.strip()
        if not query or len(query) > 128 or args.limit < 1 or args.limit > 50:
            raise MoneyCraftError("usage_error", "search query/limit is invalid", exit_code=EXIT_USAGE)
        if provider == "fred":
            params = {"search_text": query, "limit": args.limit}
            return "search", "fred://series/search", params, {"query": query, "limit": args.limit}
        if provider == "yfinance":
            params = {"query": query, "limit": args.limit}
            return "search", "yfinance://search", params, dict(params)
        params = {"q": query, "asset_type": "a-share", "limit": args.limit}
        return "search", "/api/meta/tickers/search", params, dict(params)
    if command == "snapshot":
        if provider == "yfinance":
            symbol = parse_yfinance_symbol(args.symbol)
            params = {"symbol": symbol}
            return "snapshot", "yfinance://snapshot", params, dict(params)
        if args.symbol is not None:
            raise MoneyCraftError("usage_error", "Fuyao snapshot uses --thscodes", exit_code=EXIT_USAGE)
        thscodes = parse_thscodes(args.thscodes)
        params = {"thscodes": ",".join(thscodes)}
        return "snapshot", "/api/a-share/prices/snapshot", params, dict(params)
    if command == "history":
        if provider == "yfinance":
            if args.adjust == "backward":
                raise MoneyCraftError(
                    "usage_error",
                    "yfinance does not expose Money Craft's backward-adjustment contract; use auto or none",
                    exit_code=EXIT_USAGE,
                )
            symbol = parse_yfinance_symbol(args.symbol)
            validate_range(args.start, args.end, max_years=10)
            params = {
                "symbol": symbol,
                "interval": args.interval,
                "start": args.start,
                "end": args.end,
                "adjust": "auto" if args.adjust in {"auto", "forward"} else "none",
            }
            return "history", "yfinance://history", params, dict(params)
        if args.symbol is not None or args.adjust == "auto":
            raise MoneyCraftError(
                "usage_error", "Fuyao history uses --thscode and forward/backward/none adjustment", exit_code=EXIT_USAGE
            )
        thscode = parse_thscodes(args.thscode, maximum=1)[0]
        validate_range(args.start, args.end, max_years=10)
        params = {
            "thscode": thscode,
            "interval": args.interval,
            "start": date_to_ms(args.start),
            "end": date_to_ms(args.end),
            "adjust": args.adjust,
        }
        output_parameters = dict(params)
        output_parameters.update({"start_date": args.start, "end_date": args.end})
        return "history", "/api/a-share/prices/historical", params, output_parameters
    if command == "valuations":
        if provider == "yfinance":
            symbol = parse_yfinance_symbol(args.symbol)
            params = {"symbol": symbol}
            return "valuations", "yfinance://valuations", params, dict(params)
        if args.symbol is not None:
            raise MoneyCraftError("usage_error", "Fuyao valuations uses --thscodes", exit_code=EXIT_USAGE)
        thscodes = parse_thscodes(args.thscodes, maximum=100)
        params = {"thscodes": ",".join(thscodes)}
        return "valuations", "/api/a-share/valuations/snapshot", params, dict(params)
    if command == "financials":
        has_start = args.start is not None
        has_end = args.end is not None
        if has_start != has_end:
            raise MoneyCraftError("usage_error", "financials requires both --start and --end", exit_code=EXIT_USAGE)
        if has_start and args.limit is not None:
            raise MoneyCraftError("usage_error", "financials limit conflicts with date range", exit_code=EXIT_USAGE)
        if provider == "yfinance":
            if has_start:
                raise MoneyCraftError(
                    "usage_error", "yfinance financial statements use period and optional limit, not a date range", exit_code=EXIT_USAGE
                )
            symbol = parse_yfinance_symbol(args.symbol)
            limit = 4 if args.limit is None else args.limit
            if limit < 1 or limit > 20:
                raise MoneyCraftError("usage_error", "financials limit must be 1..20", exit_code=EXIT_USAGE)
            params = {"symbol": symbol, "period": args.period, "limit": limit}
            return f"financials.{args.statement}", f"yfinance://financials/{args.statement}", params, dict(params)
        if args.symbol is not None:
            raise MoneyCraftError("usage_error", "Fuyao financials uses --thscode", exit_code=EXIT_USAGE)
        thscode = parse_thscodes(args.thscode, maximum=1)[0]
        params = {"thscode": thscode, "period": args.period}
        output_parameters = dict(params)
        if has_start:
            validate_range(args.start, args.end, max_years=10)
            params.update({"start": date_to_ms(args.start), "end": date_to_ms(args.end)})
            output_parameters.update(params)
            output_parameters.update({"start_date": args.start, "end_date": args.end})
        else:
            limit = 4 if args.limit is None else args.limit
            if limit < 1 or limit > 20:
                raise MoneyCraftError("usage_error", "financials limit must be 1..20", exit_code=EXIT_USAGE)
            params["limit"] = limit
            output_parameters["limit"] = limit
        paths = {
            "income": "/api/a-share/financials/income-statements",
            "balance": "/api/a-share/financials/balance-sheets",
            "cash-flow": "/api/a-share/financials/cash-flow-statements",
        }
        return f"financials.{args.statement}", paths[args.statement], params, output_parameters
    if command == "indicators":
        if provider != "fuyao":
            raise MoneyCraftError("usage_error", "financial indicators are only available from Fuyao", exit_code=EXIT_USAGE)
        thscode = parse_thscodes(args.thscode, maximum=1)[0]
        if not REPORT_RE.fullmatch(args.report):
            raise MoneyCraftError("usage_error", "report must match YYYY-1 through YYYY-4", exit_code=EXIT_USAGE)
        params = {"thscode": thscode, "report": args.report}
        return "indicators", "/api/a-share/financials/indicators", params, dict(params)
    if command == "corporate-actions":
        if args.start and args.end:
            validate_range(args.start, args.end)
        elif args.start:
            parse_iso_date(args.start)
        elif args.end:
            parse_iso_date(args.end)
        if provider == "yfinance":
            symbol = parse_yfinance_symbol(args.symbol)
            params = {"symbol": symbol, "start": args.start, "end": args.end}
            return "corporate-actions", "yfinance://corporate-actions", params, dict(params)
        if args.symbol is not None:
            raise MoneyCraftError("usage_error", "Fuyao corporate actions uses --thscode", exit_code=EXIT_USAGE)
        thscode = parse_thscodes(args.thscode, maximum=1)[0]
        params = {"thscode": thscode, "from": args.start, "to": args.end}
        return "corporate-actions", "/api/a-share/corporate-actions/adjustment-factors", params, dict(params)
    if command == "calendar":
        if provider != "fuyao":
            raise MoneyCraftError("usage_error", "trading calendar is only available from Fuyao", exit_code=EXIT_USAGE)
        if args.start and args.end:
            validate_range(args.start, args.end)
        elif args.start:
            parse_iso_date(args.start)
        elif args.end:
            parse_iso_date(args.end)
        return "calendar", "/api/a-share/calendar/trading-days", {}, {"start": args.start, "end": args.end}
    if command == "series":
        series_id = parse_fred_series_id(args.series_id)
        params: dict[str, Any] = {"series_id": series_id}
        if args.as_known_on:
            parse_iso_date(args.as_known_on)
            params.update({"realtime_start": args.as_known_on, "realtime_end": args.as_known_on})
        return "series", "fred://series", params, {
            "series_id": series_id,
            "as_known_on": args.as_known_on,
        }
    if command == "observations":
        series_id = parse_fred_series_id(args.series_id)
        if args.start and args.end:
            validate_range(args.start, args.end)
        elif args.start:
            parse_iso_date(args.start)
        elif args.end:
            parse_iso_date(args.end)
        if args.as_known_on:
            parse_iso_date(args.as_known_on)
        if args.limit < 1 or args.limit > 10000:
            raise MoneyCraftError("usage_error", "FRED observations limit must be 1..10000", exit_code=EXIT_USAGE)
        params = {
            "series_id": series_id,
            "observation_start": args.start,
            "observation_end": args.end,
            "units": args.units,
            "limit": args.limit,
            "realtime_start": args.as_known_on,
            "realtime_end": args.as_known_on,
        }
        return "observations", "fred://series/observations", params, {
            "series_id": series_id,
            "start": args.start,
            "end": args.end,
            "units": args.units,
            "limit": args.limit,
            "as_known_on": args.as_known_on,
        }
    if command == "vintages":
        series_id = parse_fred_series_id(args.series_id)
        if args.start and args.end:
            validate_range(args.start, args.end)
        elif args.start:
            parse_iso_date(args.start)
        elif args.end:
            parse_iso_date(args.end)
        if args.limit < 1 or args.limit > 10000:
            raise MoneyCraftError("usage_error", "FRED vintages limit must be 1..10000", exit_code=EXIT_USAGE)
        params = {
            "series_id": series_id,
            "realtime_start": args.start,
            "realtime_end": args.end,
            "limit": args.limit,
        }
        return "vintages", "fred://series/vintagedates", params, {
            "series_id": series_id,
            "start": args.start,
            "end": args.end,
            "limit": args.limit,
        }
    raise MoneyCraftError("usage_error", f"unsupported data command: {command}", exit_code=EXIT_USAGE)


def run_data(args: argparse.Namespace) -> int:
    operation, path, params, output_parameters = prepare_operation(args)
    provider = args.resolved_provider
    args.resolved_operation = operation
    args.sanitized_parameters = output_parameters
    authentication = "none"
    forbidden_values: tuple[str, ...] = ()
    if provider == "fuyao":
        credential = load_fuyao_credential()
        authentication = credential.capture_label
        forbidden_values = (credential.api_key,)
        client = FuyaoClient(credential.api_key)
        result = client.request(operation, path, params)
    elif provider == "fred":
        try:
            fred_credential = fred_adapter.load_credential()
            adapter_result = fred_adapter.FredClient(
                fred_credential.api_key,
                user_agent=f"money-craft/{VERSION}",
            ).request(operation, params)
        except fred_adapter.FredAdapterError as exc:
            if exc.kind in {"missing_configuration", "invalid_configuration"}:
                exit_code = EXIT_CONFIG
            elif exc.retryable:
                exit_code = EXIT_TRANSIENT
            elif exc.kind in {"malformed_response", "response_too_large"}:
                exit_code = EXIT_SCHEMA
            else:
                exit_code = EXIT_PROVIDER
            raise MoneyCraftError(
                exc.kind,
                sanitize_message(exc),
                code=exc.code,
                retryable=exc.retryable,
                exit_code=exit_code,
            ) from exc
        authentication = fred_credential.capture_label
        forbidden_values = (fred_credential.api_key,)
        result = ProviderResult(
            operation=operation,
            path=adapter_result.path,
            parameters=params,
            payload={"request_id": None, "data": adapter_result.data},
            raw_response=adapter_result.raw_response,
            fetched_at=adapter_result.fetched_at,
            provider="fred",
        )
    else:
        try:
            adapter_result = yfinance_adapter.YFinanceClient().request(operation, params)
        except yfinance_adapter.YFinanceAdapterError as exc:
            raise MoneyCraftError(
                exc.kind,
                sanitize_message(exc),
                retryable=exc.retryable,
                exit_code=EXIT_TRANSIENT if exc.retryable else EXIT_PROVIDER,
            ) from exc
        result = ProviderResult(
            operation=operation,
            path=path,
            parameters=params,
            payload={"request_id": None, "data": adapter_result.data},
            raw_response=adapter_result.adapter_export,
            fetched_at=adapter_result.fetched_at,
            provider="yfinance",
        )
    data = result.payload.get("data")
    warnings: list[str] = []
    if provider == "fuyao" and args.data_command == "calendar" and (args.start or args.end):
        data = filter_calendar(data, args.start, args.end)
        warnings.append("calendar date range was filtered locally; the provider endpoint has a fixed one-year window")
    if provider == "yfinance":
        warnings.append(
            "yfinance/Yahoo data is secondary research data for personal use; verify decision-critical facts against official filings"
        )
    if provider == "fred":
        warnings.extend(
            [
                "This product uses the FRED® API but is not endorsed or certified by the Federal Reserve Bank of St. Louis.",
                "FRED series can be revised and third-party series may have separate rights; preserve metadata and use ALFRED as-known-on dates for historical claims.",
            ]
        )
    data_object = result.payload.get("data")
    source_timestamp = data_object.get("timestamp") if isinstance(data_object, dict) else None
    response: dict[str, Any] = {
        "schema": "money-craft.data-response.v1",
        "ok": True,
        "provider": provider,
        "operation": operation,
        "request_id": result.payload.get("request_id"),
        "fetched_at": result.fetched_at,
        "source_timestamp_ms": source_timestamp,
        "parameters": output_parameters,
        "data": data,
        "warnings": warnings,
    }
    capture_args = validate_capture_args(args.capture_dir, args.source_id)
    if capture_args:
        destination = capture_result(
            capture_args[0],
            capture_args[1],
            result,
            output_parameters=output_parameters,
            authentication=authentication,
            forbidden_values=forbidden_values,
        )
        response["capture"] = {
            "source_id": capture_args[1],
            "path": str(destination),
        }
    print_json(response)
    return 0


def run_audit(args: argparse.Namespace) -> int:
    path = Path(args.report_path).expanduser().resolve()
    if args.audit_command == "report":
        from report_audit import audit_file

        result = audit_file(path)
    elif args.audit_command == "financial":
        from financial_rigor import audit_file

        result = audit_file(path)
    else:
        from financial_reconciliation import audit_file

        result = audit_file(path)
    print_json(result)
    return 0 if result["valid"] else EXIT_PROVIDER


def research_provider(mode: str, *, adapter: str, security_supported: bool) -> dict[str, Any]:
    if mode == "disabled":
        return {
            "mode": mode,
            "adapter": adapter,
            "configured": False,
            "configuration_source": None,
            "network_checked": False,
        }
    if not security_supported:
        return {
            "mode": mode,
            "adapter": adapter,
            "configured": False,
            "configuration_source": None,
            "network_checked": False,
        }
    if adapter == "yfinance":
        configured = importlib.util.find_spec("yfinance") is not None
        if not configured and mode == "required":
            raise WorkflowError(
                "missing_optional_dependency",
                "install skills/money-craft/requirements-yfinance.txt in the active Python environment",
                exit_code=EXIT_CONFIG,
            )
        return {
            "mode": mode,
            "adapter": adapter,
            "configured": configured,
            "configuration_source": "python-package" if configured else None,
            "package_version": yfinance_adapter.installed_version(),
            "network_checked": False,
        }
    try:
        credential = load_fuyao_credential()
    except MoneyCraftError as exc:
        if exc.kind == "missing_configuration" and mode == "auto":
            return {
                "mode": mode,
                "adapter": adapter,
                "configured": False,
                "configuration_source": None,
                "network_checked": False,
            }
        raise WorkflowError(exc.kind, sanitize_message(exc), exit_code=exc.exit_code) from exc
    return {
        "mode": mode,
        "adapter": adapter,
        "configured": True,
        "configuration_source": credential.source,
        "network_checked": False,
    }


def run_research(args: argparse.Namespace) -> int:
    try:
        if args.research_command in {"plan", "init"}:
            supports_fuyao = bool(args.thscode)
            if not supports_fuyao and args.security_id:
                supports_fuyao = thscode_from_security_id(args.security_id) is not None
            supports_yfinance = bool(
                args.security_id and yfinance_symbol_from_security_id(args.security_id) is not None
            )
            adapter = args.provider
            if adapter == "auto":
                adapter = "fuyao" if supports_fuyao else "yfinance"
            security_supported = supports_fuyao if adapter == "fuyao" else supports_yfinance
            plan = company_research_plan(
                security=args.security,
                security_id=args.security_id,
                thscode=args.thscode,
                base_currency=args.base_currency,
                as_of=args.as_of,
                latest_report=args.latest_report,
                latest_report_end=args.latest_report_end,
                latest_annual_report=args.latest_annual_report,
                provider=research_provider(
                    args.provider_mode,
                    adapter=adapter,
                    security_supported=security_supported,
                ),
            )
            if args.research_command == "plan":
                result = plan
            else:
                run_id = None
                workspace = args.workspace
                if workspace is None:
                    workspace, run_id = research_run.allocate_default_workspace(
                        plan,
                        root=args.output_root,
                    )
                result = research_run.initialize_workspace(
                    workspace,
                    plan,
                    template_root=SKILL_ROOT / "templates",
                    run_id=run_id,
                )
            print_json(result)
            return 0
        if args.research_command == "collect":
            _root, plan, case, _state = research_run.load_workspace(args.workspace)
            adapter = str(plan.get("provider", {}).get("adapter", "fuyao"))
            if plan.get("provider", {}).get("mode") == "disabled":
                raise WorkflowError("provider_disabled", "research workspace explicitly disables the structured-data provider")
            if not case["operations"]:
                raise WorkflowError(
                    "provider_unavailable",
                    "research workspace has no executable provider operations; use official evidence imports",
                )
            if adapter == "fuyao":
                try:
                    load_fuyao_credential()
                except MoneyCraftError as exc:
                    raise WorkflowError(exc.kind, sanitize_message(exc), exit_code=exc.exit_code) from exc
            elif importlib.util.find_spec("yfinance") is None:
                raise WorkflowError(
                    "missing_optional_dependency",
                    "install skills/money-craft/requirements-yfinance.txt in the active Python environment",
                    exit_code=EXIT_CONFIG,
                )
            result = research_run.collect_workspace(
                args.workspace,
                runtime=Path(__file__).resolve(),
                resume=args.resume,
            )
            print_json(result)
            return 0 if result["valid"] else EXIT_PROVIDER
        if args.research_command == "import-official":
            result = research_run.import_official_source(
                args.workspace,
                source_id=args.source_id,
                source_file=args.file,
                url=args.url,
                title=args.title,
                retrieved_on=args.retrieved_on,
            )
            print_json(result)
            return 0
        if args.research_command == "status":
            print_json(research_run.research_status(args.workspace))
            return 0
        if args.research_command == "finalize":
            result = research_run.finalize_workspace(args.workspace)
            print_json(result)
            return 0 if result["valid"] else EXIT_PROVIDER
        raise WorkflowError("unsupported_workflow", "unsupported research command")
    except research_run.ResearchRunError as exc:
        raise WorkflowError(exc.kind, sanitize_message(exc), exit_code=exc.exit_code) from exc


def run_thesis(args: argparse.Namespace) -> int:
    if args.thesis_command == "prepare-update":
        result = prepare_thesis_update(args.previous, as_of=args.as_of)
    elif args.thesis_command == "diff":
        result = thesis_diff(args.previous, args.current)
    else:
        raise WorkflowError("unsupported_workflow", "unsupported thesis command")
    print_json(result)
    return 0


def run_track(args: argparse.Namespace) -> int:
    try:
        if args.track_command == "init":
            result = tracking_workflow.initialize_tracking(
                args.tracking_root,
                as_of=args.as_of,
                template_root=SKILL_ROOT / "templates",
                previous=args.previous,
                source_revision=args.source_revision,
                workspace=args.workspace,
            )
        elif args.track_command == "check":
            result = tracking_workflow.finalize_tracking(args.workspace)
        elif args.track_command == "status":
            result = tracking_workflow.tracking_status(args.tracking_root)
        elif args.track_command == "verify":
            result = tracking_workflow.verify_tracking(
                args.tracking_root,
                require_read_only=not args.no_require_read_only,
            )
        else:
            raise WorkflowError("unsupported_workflow", "unsupported track command")
    except tracking_workflow.TrackingError as exc:
        raise WorkflowError(exc.kind, sanitize_message(exc), exit_code=exc.exit_code) from exc
    print_json(result)
    return 0 if result.get("valid", True) else EXIT_PROVIDER


def run_report(args: argparse.Namespace) -> int:
    try:
        if args.report_command == "verify":
            result = report_renderer.verify_rendered_report(
                args.source.expanduser().resolve(),
                args.html.expanduser().resolve(),
                args.pdf.expanduser().resolve() if args.pdf else None,
            )
            print_json(result)
            return 0 if result["valid"] else EXIT_PROVIDER
        if args.report_command != "render":
            raise WorkflowError("unsupported_workflow", "unsupported report command")
        source = args.source.expanduser().resolve()
        output_html, output_pdf = report_renderer.resolve_output_paths(
            source,
            output_dir=args.output_dir,
            output_html=args.output_html,
            output_pdf=args.output_pdf,
            html_only=args.html_only,
        )
        result = report_renderer.render_report(
            source,
            output_html=output_html,
            output_pdf=output_pdf,
            evidence_manifest=args.evidence_manifest.expanduser().resolve()
            if args.evidence_manifest
            else None,
            audit_path=args.audit.expanduser().resolve() if args.audit else None,
            revision_manifest=args.revision_manifest.expanduser().resolve()
            if args.revision_manifest
            else None,
            archive_manifest=args.archive_manifest.expanduser().resolve()
            if args.archive_manifest
            else None,
            charts=not args.no_charts,
            requested_theme=args.theme,
        )
    except report_renderer.ReportRenderError as exc:
        raise WorkflowError("report_render_failed", sanitize_message(exc), exit_code=EXIT_CONFIG) from exc
    print_json(result)
    return 0


def error_payload(
    exc: MoneyCraftError,
    operation: str | None = None,
    parameters: Mapping[str, Any] | None = None,
    provider: str | None = None,
) -> dict[str, Any]:
    return {
        "schema": "money-craft.data-response.v1",
        "ok": False,
        "provider": provider if operation else None,
        "operation": operation,
        "request_id": exc.request_id,
        "fetched_at": utc_now(),
        "source_timestamp_ms": None,
        "parameters": dict(parameters or {}),
        "data": None,
        "warnings": [],
        "error": {
            "kind": exc.kind,
            "code": exc.code,
            "message": sanitize_message(exc),
            "retryable": exc.retryable,
        },
    }


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        if args.command == "doctor":
            payload = doctor_payload()
            print_json(payload)
            return 0 if payload["python"]["supported"] and payload["runtime"]["canonical_files_present"] else 1
        if args.command == "self-test":
            payload = self_test_payload()
            print_json(payload)
            return 0 if payload["runtime_valid"] else 1
        if args.command == "data":
            return run_data(args)
        if args.command == "audit":
            return run_audit(args)
        if args.command == "research":
            return run_research(args)
        if args.command == "thesis":
            return run_thesis(args)
        if args.command == "track":
            return run_track(args)
        if args.command == "report":
            return run_report(args)
        raise MoneyCraftError("usage_error", "unsupported command", exit_code=EXIT_USAGE)
    except WorkflowError as exc:
        print_json(
            {
                "schema": "money-craft.workflow-error.v1",
                "valid": False,
                "error": {"kind": exc.kind, "message": sanitize_message(exc)},
            }
        )
        return exc.exit_code
    except MoneyCraftError as exc:
        operation = (
            getattr(args, "resolved_operation", getattr(args, "data_command", None))
            if args.command == "data"
            else None
        )
        parameters = getattr(args, "sanitized_parameters", None) if args.command == "data" else None
        provider = getattr(args, "resolved_provider", getattr(args, "provider", "fuyao")) if args.command == "data" else None
        print_json(error_payload(exc, operation, parameters, provider))
        return exc.exit_code
    except OSError as exc:
        wrapped = MoneyCraftError("local_io_error", sanitize_message(exc), exit_code=EXIT_PROVIDER)
        operation = (
            getattr(args, "resolved_operation", getattr(args, "data_command", None))
            if args.command == "data"
            else None
        )
        parameters = getattr(args, "sanitized_parameters", None) if args.command == "data" else None
        provider = getattr(args, "resolved_provider", getattr(args, "provider", "fuyao")) if args.command == "data" else None
        print_json(error_payload(wrapped, operation, parameters, provider))
        return wrapped.exit_code


if __name__ == "__main__":
    try:
        runtime_paths.load_explicit_env_file()
        maybe_reexec_data_runtime()
        raise SystemExit(main())
    except runtime_paths.RuntimePathError as exc:
        print_json(
            error_payload(
                MoneyCraftError(
                    "invalid_configuration",
                    sanitize_message(exc),
                    exit_code=EXIT_CONFIG,
                )
            )
        )
        raise SystemExit(EXIT_CONFIG)
