#!/usr/bin/env python3
"""Portable Money Craft runtime and Fuyao A-share REST client."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import shutil
import socket
import stat
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

SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_ROOT = SCRIPT_DIR.parent
VERSION = (SKILL_ROOT / "VERSION").read_text(encoding="utf-8").strip()
BASE_URL = "https://fuyao.aicubes.cn"
API_KEY_ENV = "FUYAO_API_KEY"
API_KEY_FILE_RELATIVE = Path(".config") / "money-craft" / "fuyao-api-key"
API_KEY_FILE_DISPLAY = "~/.config/money-craft/fuyao-api-key"
MAX_API_KEY_BYTES = 4096
SHANGHAI = ZoneInfo("Asia/Shanghai")
MAX_RESPONSE_BYTES = 10 * 1024 * 1024
REQUEST_TIMEOUT_SECONDS = 30
MAX_ATTEMPTS = 3
RETRY_DELAYS = (0.5, 1.0)
THSCODE_RE = re.compile(r"^\d{6}\.(?:SH|SZ|BJ)$")
SOURCE_ID_RE = re.compile(r"^S\d{2,4}$")
REPORT_RE = re.compile(r"^(?:19|20)\d{2}-[1-4]$")
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


def fuyao_api_key_path(home: Path | None = None) -> Path:
    return (home if home is not None else Path.home()) / API_KEY_FILE_RELATIVE


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

    path = fuyao_api_key_path(home)
    try:
        metadata = path.lstat()
    except FileNotFoundError as exc:
        raise MoneyCraftError(
            "missing_configuration",
            f"configure {API_KEY_ENV} or {API_KEY_FILE_DISPLAY}",
            exit_code=EXIT_CONFIG,
        ) from exc
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise MoneyCraftError(
            "invalid_configuration",
            f"{API_KEY_FILE_DISPLAY} must be a regular file, not a symlink",
            exit_code=EXIT_CONFIG,
        )
    if hasattr(os, "getuid") and metadata.st_uid != os.getuid():
        raise MoneyCraftError(
            "invalid_configuration",
            f"{API_KEY_FILE_DISPLAY} must be owned by the current user",
            exit_code=EXIT_CONFIG,
        )
    if stat.S_IMODE(metadata.st_mode) & 0o077:
        raise MoneyCraftError(
            "invalid_configuration",
            f"{API_KEY_FILE_DISPLAY} permissions must be 0600 or stricter",
            exit_code=EXIT_CONFIG,
        )
    if metadata.st_size < 1 or metadata.st_size > MAX_API_KEY_BYTES:
        raise MoneyCraftError(
            "invalid_configuration",
            f"{API_KEY_FILE_DISPLAY} has an invalid size",
            exit_code=EXIT_CONFIG,
        )
    try:
        value = path.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeDecodeError) as exc:
        raise MoneyCraftError(
            "invalid_configuration",
            f"cannot read {API_KEY_FILE_DISPLAY}: {sanitize_message(exc)}",
            exit_code=EXIT_CONFIG,
        ) from exc
    if not value or "\n" in value or "\r" in value:
        raise MoneyCraftError(
            "invalid_configuration",
            f"{API_KEY_FILE_DISPLAY} must contain exactly one non-empty line",
            exit_code=EXIT_CONFIG,
        )
    return FuyaoCredential(
        api_key=value,
        source="secure-file",
        capture_label=f"secure-file:{API_KEY_FILE_DISPLAY}",
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


def parse_thscodes(value: str, *, maximum: int = 100) -> list[str]:
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
            "provider": "fuyao",
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
            "provider": "fuyao",
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
    search.add_argument("--query", required=True)
    search.add_argument("--limit", type=int, default=10)
    add_capture_options(search)
    snapshot = data_subparsers.add_parser("snapshot")
    snapshot.add_argument("--thscodes", required=True)
    add_capture_options(snapshot)
    history = data_subparsers.add_parser("history")
    history.add_argument("--thscode", required=True)
    history.add_argument("--start", required=True)
    history.add_argument("--end", required=True)
    history.add_argument("--interval", choices=["1d"], default="1d")
    history.add_argument("--adjust", choices=["none", "forward", "backward"], default="forward")
    add_capture_options(history)
    valuations = data_subparsers.add_parser("valuations")
    valuations.add_argument("--thscodes", required=True)
    add_capture_options(valuations)
    financials = data_subparsers.add_parser("financials")
    financials.add_argument("--thscode", required=True)
    financials.add_argument("--statement", choices=["income", "balance", "cash-flow"], required=True)
    financials.add_argument("--period", choices=["annual", "quarterly"], default="annual")
    financials.add_argument("--limit", type=int)
    financials.add_argument("--start")
    financials.add_argument("--end")
    add_capture_options(financials)
    indicators = data_subparsers.add_parser("indicators")
    indicators.add_argument("--thscode", required=True)
    indicators.add_argument("--report", required=True)
    add_capture_options(indicators)
    actions = data_subparsers.add_parser("corporate-actions")
    actions.add_argument("--thscode", required=True)
    actions.add_argument("--start")
    actions.add_argument("--end")
    add_capture_options(actions)
    calendar = data_subparsers.add_parser("calendar")
    calendar.add_argument("--start")
    calendar.add_argument("--end")
    add_capture_options(calendar)

    audit = subparsers.add_parser("audit")
    audit_subparsers = audit.add_subparsers(dest="audit_command", required=True)
    for name in ("report", "financial"):
        audit_parser = audit_subparsers.add_parser(name)
        audit_parser.add_argument("report_path")
        audit_parser.add_argument("--json", action="store_true")
    return parser


def doctor_payload() -> dict[str, Any]:
    credential: FuyaoCredential | None = None
    credential_error: MoneyCraftError | None = None
    try:
        credential = load_fuyao_credential()
    except MoneyCraftError as exc:
        credential_error = exc
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
                for path in ("SKILL.md", "VERSION", "scripts/money_craft.py")
            ),
        },
        "fuyao": {
            "configured": credential is not None,
            "configuration_source": credential.source if credential else None,
            "environment_variable": API_KEY_ENV,
            "secure_file": API_KEY_FILE_DISPLAY,
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
    output_parameters: dict[str, Any]
    if command == "search":
        query = args.query.strip()
        if not query or len(query) > 128 or args.limit < 1 or args.limit > 50:
            raise MoneyCraftError("usage_error", "search query/limit is invalid", exit_code=EXIT_USAGE)
        params = {"q": query, "asset_type": "a-share", "limit": args.limit}
        return "search", "/api/meta/tickers/search", params, dict(params)
    if command == "snapshot":
        thscodes = parse_thscodes(args.thscodes)
        params = {"thscodes": ",".join(thscodes)}
        return "snapshot", "/api/a-share/prices/snapshot", params, dict(params)
    if command == "history":
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
        thscodes = parse_thscodes(args.thscodes, maximum=100)
        params = {"thscodes": ",".join(thscodes)}
        return "valuations", "/api/a-share/valuations/snapshot", params, dict(params)
    if command == "financials":
        thscode = parse_thscodes(args.thscode, maximum=1)[0]
        has_start = args.start is not None
        has_end = args.end is not None
        if has_start != has_end:
            raise MoneyCraftError("usage_error", "financials requires both --start and --end", exit_code=EXIT_USAGE)
        if has_start and args.limit is not None:
            raise MoneyCraftError("usage_error", "financials limit conflicts with date range", exit_code=EXIT_USAGE)
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
        thscode = parse_thscodes(args.thscode, maximum=1)[0]
        if not REPORT_RE.fullmatch(args.report):
            raise MoneyCraftError("usage_error", "report must match YYYY-1 through YYYY-4", exit_code=EXIT_USAGE)
        params = {"thscode": thscode, "report": args.report}
        return "indicators", "/api/a-share/financials/indicators", params, dict(params)
    if command == "corporate-actions":
        thscode = parse_thscodes(args.thscode, maximum=1)[0]
        if args.start and args.end:
            validate_range(args.start, args.end)
        elif args.start:
            parse_iso_date(args.start)
        elif args.end:
            parse_iso_date(args.end)
        params = {"thscode": thscode, "from": args.start, "to": args.end}
        return "corporate-actions", "/api/a-share/corporate-actions/adjustment-factors", params, dict(params)
    if command == "calendar":
        if args.start and args.end:
            validate_range(args.start, args.end)
        elif args.start:
            parse_iso_date(args.start)
        elif args.end:
            parse_iso_date(args.end)
        return "calendar", "/api/a-share/calendar/trading-days", {}, {"start": args.start, "end": args.end}
    raise MoneyCraftError("usage_error", f"unsupported data command: {command}", exit_code=EXIT_USAGE)


def run_data(args: argparse.Namespace) -> int:
    operation, path, params, output_parameters = prepare_operation(args)
    args.resolved_operation = operation
    args.sanitized_parameters = output_parameters
    credential = load_fuyao_credential()
    client = FuyaoClient(credential.api_key)
    result = client.request(operation, path, params)
    data = result.payload.get("data")
    warnings: list[str] = []
    if args.data_command == "calendar" and (args.start or args.end):
        data = filter_calendar(data, args.start, args.end)
        warnings.append("calendar date range was filtered locally; the provider endpoint has a fixed one-year window")
    data_object = result.payload.get("data")
    source_timestamp = data_object.get("timestamp") if isinstance(data_object, dict) else None
    response: dict[str, Any] = {
        "schema": "money-craft.data-response.v1",
        "ok": True,
        "provider": "fuyao",
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
            authentication=credential.capture_label,
            forbidden_values=(credential.api_key,),
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
    else:
        from financial_rigor import audit_file

        result = audit_file(path)
    print_json(result)
    return 0 if result["valid"] else EXIT_PROVIDER


def error_payload(
    exc: MoneyCraftError,
    operation: str | None = None,
    parameters: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "schema": "money-craft.data-response.v1",
        "ok": False,
        "provider": "fuyao" if operation else None,
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
        raise MoneyCraftError("usage_error", "unsupported command", exit_code=EXIT_USAGE)
    except MoneyCraftError as exc:
        operation = (
            getattr(args, "resolved_operation", getattr(args, "data_command", None))
            if args.command == "data"
            else None
        )
        parameters = getattr(args, "sanitized_parameters", None) if args.command == "data" else None
        print_json(error_payload(exc, operation, parameters))
        return exc.exit_code
    except OSError as exc:
        wrapped = MoneyCraftError("local_io_error", sanitize_message(exc), exit_code=EXIT_PROVIDER)
        operation = (
            getattr(args, "resolved_operation", getattr(args, "data_command", None))
            if args.command == "data"
            else None
        )
        parameters = getattr(args, "sanitized_parameters", None) if args.command == "data" else None
        print_json(error_payload(wrapped, operation, parameters))
        return wrapped.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
