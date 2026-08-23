#!/usr/bin/env python3
"""Portable, evidence-gated research run workspaces."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import unicodedata
import uuid
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

import financial_rigor
import report_audit
import research_workflow

PLAN_SCHEMA = "money-craft.company-research-plan.v1"
CASE_SCHEMA = "money-craft.research-case.v1"
STATE_SCHEMA = "money-craft.research-run-state.v1"
INIT_SCHEMA = "money-craft.research-init.v1"
COLLECTION_SCHEMA = "money-craft.research-collection.v1"
IMPORT_SCHEMA = "money-craft.official-import.v1"
STATUS_SCHEMA = "money-craft.research-status.v1"
FINALIZE_SCHEMA = "money-craft.research-finalize.v1"
RECEIPT_SCHEMA = "money-craft.research-completion-receipt.v1"
MANIFEST_SCHEMA = "money-craft.public-evidence-manifest.v1"
PROVIDER_DOCUMENTATION = "https://fuyao.aicubes.cn/docs/api-reference/overview/"
SOURCE_ID_RE = re.compile(r"^S\d{2,4}$")
SECRET_RE = re.compile(rb"sk-fuyao-[A-Za-z0-9_-]{12,}")
MAX_JSON_BYTES = 32 * 1024 * 1024
MAX_DOCUMENT_BYTES = 5 * 1024 * 1024
MAX_OFFICIAL_SOURCE_BYTES = 100 * 1024 * 1024
MAX_STATE_EVENTS = 1000
SHANGHAI = ZoneInfo("Asia/Shanghai")
OUTPUT_ROOT_ENV = "MONEY_CRAFT_OUTPUT_ROOT"
DEFAULT_OUTPUT_ROOT_RELATIVE = Path("Documents") / "sixseven" / "money"
RECEIPT_BOUND_FILES = {
    "plan.json",
    "case.json",
    "evidence-manifest.json",
    "report.md",
    "thesis.md",
    "report-audit.json",
    "report-financial-audit.json",
    "thesis-audit.json",
    "thesis-financial-audit.json",
}

Runner = Callable[..., subprocess.CompletedProcess[str]]


class ResearchRunError(RuntimeError):
    """A research workspace is unsafe, inconsistent, or incomplete."""

    def __init__(self, kind: str, message: str, *, exit_code: int = 4) -> None:
        super().__init__(message)
        self.kind = kind
        self.exit_code = exit_code


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z")


def encoded_json(payload: dict[str, Any]) -> bytes:
    data = (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    if len(data) > MAX_JSON_BYTES:
        raise ResearchRunError("artifact_too_large", "research JSON artifact exceeds the size limit")
    if SECRET_RE.search(data):
        raise ResearchRunError("secret_material", "secret-like material rejected from research workspace")
    return data


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def atomic_bytes(path: Path, data: bytes, *, replace: bool = True) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    staging = path.with_name(f".{path.name}.staging.{os.getpid()}.{uuid.uuid4().hex}")
    try:
        with staging.open("xb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        if not replace and (path.exists() or path.is_symlink()):
            raise ResearchRunError("existing_artifact", f"artifact already exists: {path.name}")
        os.replace(staging, path)
    finally:
        if staging.exists():
            staging.unlink()


def atomic_json(path: Path, payload: dict[str, Any], *, replace: bool = True) -> None:
    atomic_bytes(path, encoded_json(payload), replace=replace)


def load_json(path: Path) -> dict[str, Any]:
    try:
        metadata = path.lstat()
    except FileNotFoundError as exc:
        raise ResearchRunError("missing_artifact", f"missing research artifact: {path.name}") from exc
    except OSError as exc:
        raise ResearchRunError("invalid_artifact", f"cannot inspect JSON artifact {path.name}: {exc}") from exc
    if path.is_symlink() or not path.is_file():
        raise ResearchRunError("invalid_artifact", f"JSON artifact must be a regular file: {path.name}")
    if metadata.st_size < 2 or metadata.st_size > MAX_JSON_BYTES:
        raise ResearchRunError("invalid_artifact", f"JSON artifact size is invalid: {path.name}")
    try:
        raw = path.read_bytes()
        if SECRET_RE.search(raw):
            raise ResearchRunError("secret_material", f"secret-like material found in {path.name}")
        payload = json.loads(raw.decode("utf-8"))
    except ResearchRunError:
        raise
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ResearchRunError("invalid_artifact", f"invalid JSON artifact {path.name}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ResearchRunError("invalid_artifact", f"JSON object required: {path.name}")
    return payload


def workspace_path(value: Path | str) -> Path:
    raw = Path(value).expanduser()
    if raw.is_symlink():
        raise ResearchRunError("invalid_workspace", "workspace must not be a symlink")
    path = raw.resolve(strict=False)
    if path.exists() and (path.is_symlink() or not path.is_dir()):
        raise ResearchRunError("invalid_workspace", "workspace must be a real directory")
    return path


def output_root(
    value: Path | str | None = None,
    *,
    environment: dict[str, str] | None = None,
    home: Path | None = None,
) -> tuple[Path, str]:
    environ = os.environ if environment is None else environment
    if value is not None:
        raw = Path(value).expanduser()
        source = "command-line"
    elif environ.get(OUTPUT_ROOT_ENV, "").strip():
        raw = Path(environ[OUTPUT_ROOT_ENV].strip()).expanduser()
        source = f"environment:{OUTPUT_ROOT_ENV}"
    else:
        raw = (home if home is not None else Path.home()) / DEFAULT_OUTPUT_ROOT_RELATIVE
        source = "default"
    if raw.is_symlink():
        raise ResearchRunError("invalid_output_root", "research output root must not be a symlink")
    resolved = raw.resolve(strict=False)
    if resolved.exists() and not resolved.is_dir():
        raise ResearchRunError("invalid_output_root", "research output root must be a directory")
    return resolved, source


def company_directory_name(plan: dict[str, Any]) -> str:
    identity = plan.get("identity")
    if not isinstance(identity, dict):
        raise ResearchRunError("invalid_plan", "plan identity is required for the research output path")
    thscode = identity.get("thscode")
    security = identity.get("security")
    if not isinstance(thscode, str) or not re.fullmatch(r"\d{6}\.(?:SH|SZ|BJ)", thscode):
        raise ResearchRunError("invalid_plan", "plan thscode is invalid for the research output path")
    if not isinstance(security, str) or not security.strip():
        raise ResearchRunError("invalid_plan", "plan security name is required for the research output path")
    normalized = unicodedata.normalize("NFKC", security).strip()
    normalized = re.sub(r"[\x00-\x1f<>:\"/\\|?*]+", "-", normalized)
    normalized = re.sub(r"\s+", "", normalized).strip(" .-")
    if not normalized:
        raise ResearchRunError("invalid_plan", "plan security name has no safe path characters")
    if len(normalized) > 80:
        normalized = normalized[:80].rstrip(" .-")
    return f"{thscode[:6]}-{normalized}"


def allocate_default_workspace(
    plan: dict[str, Any],
    *,
    root: Path | str | None = None,
    environment: dict[str, str] | None = None,
    home: Path | None = None,
) -> tuple[Path, str]:
    archive_root, _source = output_root(root, environment=environment, home=home)
    as_of = plan.get("as_of")
    try:
        dt.date.fromisoformat(str(as_of))
    except ValueError as exc:
        raise ResearchRunError("invalid_plan", "plan as_of must be an ISO date") from exc
    research_root = archive_root / company_directory_name(plan) / str(as_of) / ".research"
    for _attempt in range(10):
        run_id = uuid.uuid4().hex
        workspace = research_root / run_id
        if not workspace.exists() and not workspace.is_symlink():
            return workspace, run_id
    raise ResearchRunError("workspace_collision", "could not allocate a unique research workspace")


def operation_slug(item: dict[str, Any]) -> str:
    operation = item["operation"]
    arguments = item["arguments"]
    if operation == "financials":
        return str(arguments["statement"])
    if operation == "corporate-actions":
        return "actions"
    return str(operation)


def operation_title(item: dict[str, Any]) -> str:
    operation = item["operation"]
    arguments = item["arguments"]
    titles = {
        "search": "Fuyao A-share ticker search",
        "snapshot": "Fuyao A-share price snapshot",
        "valuations": "Fuyao A-share valuation snapshot",
        "history": "Fuyao forward-adjusted daily price history",
        "corporate-actions": "Fuyao corporate-action adjustment factors",
        "calendar": "Fuyao trading calendar",
    }
    if operation in titles:
        return titles[operation]
    if operation == "financials":
        return f"Fuyao {arguments['period']} {arguments['statement']} statements"
    if operation == "indicators":
        return f"Fuyao {arguments['report']} financial indicators"
    raise ResearchRunError("invalid_plan", f"unsupported provider operation: {operation}")


def derived_case(plan: dict[str, Any], plan_sha256: str) -> dict[str, Any]:
    if plan.get("schema") != PLAN_SCHEMA:
        raise ResearchRunError("invalid_plan", f"plan schema must be {PLAN_SCHEMA}")
    identity = plan.get("identity")
    operations = plan.get("provider_operations")
    requirements = plan.get("official_evidence_requirements")
    if not isinstance(identity, dict) or not isinstance(operations, list) or not operations:
        raise ResearchRunError("invalid_plan", "plan identity and provider operations are required")
    if not isinstance(requirements, list) or not requirements:
        raise ResearchRunError("invalid_plan", "official evidence requirements are required")
    seen: set[str] = set()
    case_operations: list[dict[str, Any]] = []
    for item in operations:
        if not isinstance(item, dict) or not isinstance(item.get("arguments"), dict):
            raise ResearchRunError("invalid_plan", "provider operation must be an object")
        source_id = item.get("id")
        if not isinstance(source_id, str) or not SOURCE_ID_RE.fullmatch(source_id) or source_id in seen:
            raise ResearchRunError("invalid_plan", "provider source IDs must be unique Sxx identifiers")
        seen.add(source_id)
        case_operations.append(
            {
                "id": source_id,
                "title": operation_title(item),
                "operation": item["operation"],
                "arguments": item["arguments"],
                "output": f"{source_id}-{operation_slug(item)}.normalized.json",
            }
        )
    official_sources: list[dict[str, Any]] = []
    for item in requirements:
        if not isinstance(item, dict):
            raise ResearchRunError("invalid_plan", "official evidence requirement must be an object")
        source_id = item.get("id")
        if not isinstance(source_id, str) or not SOURCE_ID_RE.fullmatch(source_id) or source_id in seen:
            raise ResearchRunError("invalid_plan", "official source IDs must be unique Sxx identifiers")
        seen.add(source_id)
        role = item.get("role")
        if not isinstance(role, str) or not role:
            raise ResearchRunError("invalid_plan", f"{source_id}.role is required")
        kind = "official-index" if "index" in role else "official-document"
        official_sources.append(
            {
                "id": source_id,
                "role": role,
                "period": item.get("period"),
                "kind": kind,
                "status": "pending",
            }
        )
    return {
        "schema": CASE_SCHEMA,
        "plan_sha256": plan_sha256,
        "identity": identity,
        "as_of": plan.get("as_of"),
        "provider_documentation": PROVIDER_DOCUMENTATION,
        "operations": case_operations,
        "official_sources": official_sources,
    }


def render_draft(template: str, plan: dict[str, Any]) -> str:
    identity = plan["identity"]
    provider_status = "configured" if plan.get("provider", {}).get("configured") is True else "unavailable"
    replacements = {
        "{{screen_or_research_or_earnings}}": "research",
        "{{security_name}}": identity["security"],
        "{{six_digit_code.exchange}}": identity["thscode"],
        "{{YYYY-MM-DD}}": plan["as_of"],
        "{{configured_or_unavailable}}": provider_status,
    }
    for marker, value in replacements.items():
        template = template.replace(marker, str(value))
    return template


def initialize_workspace(
    workspace: Path | str,
    plan: dict[str, Any],
    *,
    template_root: Path,
    run_id: str | None = None,
) -> dict[str, Any]:
    root = workspace_path(workspace)
    if root.exists() or root.is_symlink():
        raise ResearchRunError("existing_workspace", "workspace already exists; choose a new workspace")
    root.parent.mkdir(parents=True, exist_ok=True)
    staging = root.with_name(f".{root.name}.staging.{uuid.uuid4().hex}")
    if staging.exists() or staging.is_symlink():
        raise ResearchRunError("existing_workspace", "workspace staging path already exists")
    staging.mkdir(mode=0o700)
    try:
        plan_data = encoded_json(plan)
        plan_sha256 = sha256_bytes(plan_data)
        case = derived_case(plan, plan_sha256)
        case_data = encoded_json(case)
        effective_run_id = run_id or uuid.uuid4().hex
        if not re.fullmatch(r"[0-9a-f]{32}", effective_run_id):
            raise ResearchRunError("invalid_run_id", "research run_id must be 32 lowercase hex characters")
        state = {
            "schema": STATE_SCHEMA,
            "run_id": effective_run_id,
            "created_at": utc_now(),
            "plan_sha256": plan_sha256,
            "revision": 1,
            "events": [
                {
                    "sequence": 1,
                    "type": "initialized",
                    "at": utc_now(),
                    "details": {
                        "thscode": plan["identity"]["thscode"],
                        "as_of": plan["as_of"],
                        "provider_operation_count": len(case["operations"]),
                    },
                }
            ],
        }
        (staging / "evidence" / "captures").mkdir(parents=True, mode=0o700)
        atomic_bytes(staging / "plan.json", plan_data, replace=False)
        atomic_bytes(staging / "case.json", case_data, replace=False)
        atomic_json(staging / "run-state.json", state, replace=False)
        for name in ("report.md", "thesis.md"):
            template = (template_root / name).read_text(encoding="utf-8")
            atomic_bytes(staging / name, render_draft(template, plan).encode("utf-8"), replace=False)
        os.replace(staging, root)
    except Exception:
        if staging.exists():
            shutil.rmtree(staging)
        raise
    return {
        "schema": INIT_SCHEMA,
        "valid": True,
        "workspace": str(root),
        "run_id": state["run_id"],
        "plan_sha256": plan_sha256,
        "provider_operation_count": len(case["operations"]),
        "official_source_count": len(case["official_sources"]),
        "network_used": False,
    }


def validate_state(state: dict[str, Any]) -> None:
    if state.get("schema") != STATE_SCHEMA:
        raise ResearchRunError("invalid_state", f"run-state schema must be {STATE_SCHEMA}")
    if not isinstance(state.get("run_id"), str) or not re.fullmatch(r"[0-9a-f]{32}", state["run_id"]):
        raise ResearchRunError("invalid_state", "run-state run_id is invalid")
    if not isinstance(state.get("revision"), int) or state["revision"] < 1:
        raise ResearchRunError("invalid_state", "run-state revision is invalid")
    events = state.get("events")
    if not isinstance(events, list) or not events or len(events) > MAX_STATE_EVENTS:
        raise ResearchRunError("invalid_state", "run-state events are invalid")
    for index, event in enumerate(events, start=1):
        if not isinstance(event, dict) or event.get("sequence") != index:
            raise ResearchRunError("invalid_state", "run-state events must be append-only and sequential")


def load_workspace(workspace: Path | str) -> tuple[Path, dict[str, Any], dict[str, Any], dict[str, Any]]:
    root = workspace_path(workspace)
    if not root.is_dir():
        raise ResearchRunError("missing_workspace", "research workspace does not exist")
    plan = load_json(root / "plan.json")
    case = load_json(root / "case.json")
    state = load_json(root / "run-state.json")
    validate_state(state)
    plan_sha256 = sha256_file(root / "plan.json")
    if state.get("plan_sha256") != plan_sha256 or case.get("plan_sha256") != plan_sha256:
        raise ResearchRunError("plan_drift", "plan.json changed after workspace initialization")
    expected_case = derived_case(plan, plan_sha256)
    if case.get("schema") != CASE_SCHEMA:
        raise ResearchRunError("invalid_case", f"case schema must be {CASE_SCHEMA}")
    for field in ("identity", "as_of", "provider_documentation", "operations"):
        if case.get(field) != expected_case[field]:
            raise ResearchRunError("case_drift", f"case.{field} no longer matches plan.json")
    actual_official = case.get("official_sources")
    if not isinstance(actual_official, list) or len(actual_official) != len(expected_case["official_sources"]):
        raise ResearchRunError("case_drift", "official source requirements no longer match plan.json")
    for expected, actual in zip(expected_case["official_sources"], actual_official):
        if not isinstance(actual, dict) or any(actual.get(key) != value for key, value in expected.items() if key != "status"):
            raise ResearchRunError("case_drift", "official source identity no longer matches plan.json")
        if actual.get("status") not in {"pending", "imported"}:
            raise ResearchRunError("invalid_case", f"{expected['id']}.status is invalid")
        allowed = set(expected)
        if actual["status"] == "imported":
            allowed.update({"title", "url", "retrieved_on", "local_path", "sha256", "bytes"})
        if set(actual) != allowed:
            raise ResearchRunError("invalid_case", f"{expected['id']} contains unsupported metadata")
    return root, plan, case, state


def record_event(root: Path, state: dict[str, Any], event_type: str, details: dict[str, Any]) -> None:
    events = state["events"]
    if len(events) >= MAX_STATE_EVENTS:
        raise ResearchRunError("state_limit", "run-state event limit reached")
    state = dict(state)
    state["revision"] += 1
    state["events"] = [
        *events,
        {
            "sequence": len(events) + 1,
            "type": event_type,
            "at": utc_now(),
            "details": details,
        },
    ]
    atomic_json(root / "run-state.json", state)


def operation_command(runtime: Path, item: dict[str, Any], capture_root: Path) -> list[str]:
    operation = item.get("operation")
    arguments = item.get("arguments")
    if not isinstance(arguments, dict):
        raise ResearchRunError("invalid_case", f"{item.get('id')}.arguments must be an object")
    option_orders = {
        "search": [("query", "--query"), ("limit", "--limit")],
        "snapshot": [("thscodes", "--thscodes")],
        "valuations": [("thscodes", "--thscodes")],
        "history": [
            ("thscode", "--thscode"),
            ("start", "--start"),
            ("end", "--end"),
            ("interval", "--interval"),
            ("adjust", "--adjust"),
        ],
        "financials": [
            ("thscode", "--thscode"),
            ("statement", "--statement"),
            ("period", "--period"),
            ("limit", "--limit"),
            ("start", "--start"),
            ("end", "--end"),
        ],
        "indicators": [("thscode", "--thscode"), ("report", "--report")],
        "corporate-actions": [("thscode", "--thscode"), ("start", "--start"), ("end", "--end")],
        "calendar": [("start", "--start"), ("end", "--end")],
    }
    if operation not in option_orders:
        raise ResearchRunError("invalid_case", f"unsupported operation: {operation}")
    option_order = option_orders[operation]
    unknown = sorted(set(arguments) - {name for name, _ in option_order})
    if unknown:
        raise ResearchRunError("invalid_case", f"unsupported arguments for {operation}: {', '.join(unknown)}")
    command = [sys.executable, str(runtime), "data", str(operation)]
    for name, option in option_order:
        if name in arguments and arguments[name] is not None:
            command.extend([option, str(arguments[name])])
    command.extend(["--capture-dir", str(capture_root), "--source-id", str(item["id"])])
    return command


def operation_status(
    item: dict[str, Any], payload: dict[str, Any], returncode: int | None = None
) -> tuple[str, dict[str, Any] | None]:
    if payload.get("schema") != "money-craft.data-response.v1" or payload.get("provider") != "fuyao":
        raise ResearchRunError("invalid_response", f"{item['id']} response identity is invalid")
    expected = str(item["operation"])
    actual = payload.get("operation")
    matches = actual == (f"financials.{item['arguments']['statement']}" if expected == "financials" else expected)
    if not matches:
        raise ResearchRunError("invalid_response", f"{item['id']} response operation is invalid")
    if payload.get("ok") is True:
        if returncode not in (None, 0):
            raise ResearchRunError("invalid_response", f"{item['id']} returned ok=true with non-zero exit")
        return "passed", None
    if payload.get("ok") is not False or returncode == 0:
        raise ResearchRunError("invalid_response", f"{item['id']} error response is invalid")
    error = payload.get("error")
    if not isinstance(error, dict):
        raise ResearchRunError("invalid_response", f"{item['id']} error details are missing")
    return "provider_gap", {
        "kind": error.get("kind"),
        "code": error.get("code"),
        "retryable": error.get("retryable") is True,
    }


def validate_identity(payload: dict[str, Any], case: dict[str, Any]) -> None:
    data = payload.get("data")
    items = data.get("item") if isinstance(data, dict) else None
    if not isinstance(items, list):
        raise ResearchRunError("identity_mismatch", "ticker search data.item must be an array")
    identity = case["identity"]
    matches = [
        item
        for item in items
        if isinstance(item, dict) and item.get("thscode") == identity["thscode"]
    ]
    if len(matches) != 1 or matches[0].get("name") != identity["security"]:
        raise ResearchRunError("identity_mismatch", "ticker search did not resolve the exact plan identity")


def normalized_payload(path: Path) -> dict[str, Any]:
    return load_json(path)


def collect_workspace(
    workspace: Path | str,
    *,
    runtime: Path,
    resume: bool = False,
    runner: Runner = subprocess.run,
) -> dict[str, Any]:
    root, _plan, case, state = load_workspace(workspace)
    evidence_root = root / "evidence"
    capture_root = evidence_root / "captures"
    capture_root.mkdir(parents=True, exist_ok=True, mode=0o700)
    results: list[dict[str, Any]] = []
    for item in case["operations"]:
        destination = evidence_root / item["output"]
        if destination.exists() or destination.is_symlink():
            if not resume or destination.is_symlink() or not destination.is_file():
                raise ResearchRunError("existing_artifact", f"normalized output already exists: {destination.name}")
            payload = normalized_payload(destination)
            status, error = operation_status(item, payload, 0 if payload.get("ok") is True else 1)
            if item["operation"] == "search" and status == "passed":
                validate_identity(payload, case)
            result = {"id": item["id"], "operation": item["operation"], "status": status, "resumed": True}
            if error:
                result["error"] = error
            results.append(result)
            if item["operation"] == "search" and status != "passed":
                break
            continue

        completed = runner(
            operation_command(runtime, item, capture_root),
            cwd=root,
            text=True,
            capture_output=True,
            check=False,
        )
        try:
            payload = json.loads(completed.stdout)
        except json.JSONDecodeError as exc:
            raise ResearchRunError("invalid_response", f"{item['id']} did not return JSON") from exc
        if not isinstance(payload, dict):
            raise ResearchRunError("invalid_response", f"{item['id']} response must be an object")
        status, error = operation_status(item, payload, completed.returncode)
        if status == "passed":
            if item["operation"] == "search":
                validate_identity(payload, case)
            capture = payload.get("capture")
            if not isinstance(capture, dict):
                raise ResearchRunError("missing_capture", f"{item['id']} passed without an evidence capture")
            capture["path"] = f"captures/{item['id']}"
        atomic_json(destination, payload, replace=False)
        result = {"id": item["id"], "operation": item["operation"], "status": status, "resumed": False}
        if error:
            result["error"] = error
        results.append(result)
        if item["operation"] == "search" and status != "passed":
            break

    passed = sum(item["status"] == "passed" for item in results)
    gaps = sum(item["status"] == "provider_gap" for item in results)
    terminal = len(results)
    total = len(case["operations"])
    summary = {
        "schema": COLLECTION_SCHEMA,
        "valid": terminal == total and gaps == 0,
        "identity_verified": bool(results and results[0]["status"] == "passed"),
        "network_boundary": "explicit-provider-collection",
        "network_requests_attempted": sum(not item["resumed"] for item in results),
        "passed": passed,
        "provider_gaps": gaps,
        "terminal": terminal,
        "total": total,
        "complete": terminal == total,
        "results": results,
    }
    atomic_json(evidence_root / "collection-summary.json", summary)
    record_event(
        root,
        state,
        "provider-collection",
        {
            "passed": passed,
            "provider_gaps": gaps,
            "terminal": terminal,
            "total": total,
            "resume": resume,
            "network_requests_attempted": summary["network_requests_attempted"],
        },
    )
    return summary


def validate_https_url(value: str) -> str:
    parsed = urlsplit(value)
    if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password:
        raise ResearchRunError("invalid_official_source", "official source URL must use HTTPS without credentials")
    return value


def validate_official_file(path: Path, kind: str) -> int:
    try:
        metadata = path.lstat()
    except FileNotFoundError as exc:
        raise ResearchRunError("missing_official_source", "official source file does not exist") from exc
    if path.is_symlink() or not path.is_file():
        raise ResearchRunError("invalid_official_source", "official source must be a regular file, not a symlink")
    if metadata.st_size < 1 or metadata.st_size > MAX_OFFICIAL_SOURCE_BYTES:
        raise ResearchRunError("invalid_official_source", "official source size is outside the allowed range")
    with path.open("rb") as handle:
        prefix = handle.read(1024).lstrip().lower()
    if kind == "official-document" and not prefix.startswith(b"%pdf-"):
        raise ResearchRunError("invalid_official_source", "official document is not a PDF")
    if kind == "official-index" and b"<" not in prefix:
        raise ResearchRunError("invalid_official_source", "official index is not HTML")
    return metadata.st_size


def import_official_source(
    workspace: Path | str,
    *,
    source_id: str,
    source_file: Path,
    url: str,
    title: str | None = None,
    retrieved_on: str | None = None,
) -> dict[str, Any]:
    root, plan, case, state = load_workspace(workspace)
    sources = case["official_sources"]
    matches = [item for item in sources if item["id"] == source_id]
    if len(matches) != 1:
        raise ResearchRunError("invalid_official_source", "source-id is not an official requirement in plan.json")
    source = matches[0]
    if source.get("status") != "pending":
        raise ResearchRunError("existing_artifact", f"official source already imported: {source_id}")
    kind = source["kind"]
    source_file = Path(os.path.abspath(source_file.expanduser()))
    size = validate_official_file(source_file, kind)
    url = validate_https_url(url)
    date_value = retrieved_on or dt.datetime.now(SHANGHAI).date().isoformat()
    try:
        dt.date.fromisoformat(date_value)
    except ValueError as exc:
        raise ResearchRunError("invalid_official_source", "retrieved-on must be YYYY-MM-DD") from exc
    resolved_title = title.strip() if isinstance(title, str) else f"{plan['identity']['security']} {source['role']}"
    if not resolved_title or len(resolved_title) > 256:
        raise ResearchRunError("invalid_official_source", "official source title must contain 1..256 characters")
    suffix = ".pdf" if kind == "official-document" else ".html"
    relative = f"{source_id}-official{suffix}"
    destination = root / "evidence" / relative
    if destination.exists() or destination.is_symlink():
        raise ResearchRunError("existing_artifact", f"official evidence already exists: {relative}")
    staging = destination.with_name(f".{destination.name}.staging.{uuid.uuid4().hex}")
    try:
        with source_file.open("rb") as input_handle, staging.open("xb") as output_handle:
            shutil.copyfileobj(input_handle, output_handle, length=1024 * 1024)
            output_handle.flush()
            os.fsync(output_handle.fileno())
        os.replace(staging, destination)
        digest = sha256_file(destination)
        updated_source = {
            **source,
            "status": "imported",
            "title": resolved_title,
            "url": url,
            "retrieved_on": date_value,
            "local_path": relative,
            "sha256": digest,
            "bytes": size,
        }
        updated_case = dict(case)
        updated_case["official_sources"] = [updated_source if item["id"] == source_id else item for item in sources]
        atomic_json(root / "case.json", updated_case)
    except Exception:
        if staging.exists():
            staging.unlink()
        if destination.exists():
            destination.unlink()
        raise
    record_event(root, state, "official-source-imported", {"source_id": source_id, "sha256": digest, "bytes": size})
    return {
        "schema": IMPORT_SCHEMA,
        "valid": True,
        "source_id": source_id,
        "kind": kind,
        "title": resolved_title,
        "url": url,
        "retrieved_on": date_value,
        "local_path": f"evidence/{relative}",
        "sha256": digest,
        "bytes": size,
    }


def inspect_provider(root: Path, case: dict[str, Any]) -> tuple[list[dict[str, Any]], list[str], list[str]]:
    results: list[dict[str, Any]] = []
    pending: list[str] = []
    gaps: list[str] = []
    for item in case["operations"]:
        path = root / "evidence" / item["output"]
        if not path.is_file() or path.is_symlink():
            pending.append(item["id"])
            results.append({"id": item["id"], "status": "pending"})
            continue
        payload = normalized_payload(path)
        status, error = operation_status(item, payload, 0 if payload.get("ok") is True else 1)
        if status == "passed":
            if item["operation"] == "search":
                validate_identity(payload, case)
            raw = root / "evidence" / "captures" / item["id"] / "response.json"
            if not raw.is_file() or raw.is_symlink():
                raise ResearchRunError("missing_capture", f"missing captured provider response: {item['id']}")
        else:
            gaps.append(item["id"])
        result = {"id": item["id"], "status": status}
        if error:
            result["error"] = error
        results.append(result)
    return results, pending, gaps


def inspect_official(root: Path, case: dict[str, Any]) -> tuple[list[dict[str, Any]], list[str]]:
    results: list[dict[str, Any]] = []
    pending: list[str] = []
    for item in case["official_sources"]:
        if item.get("status") == "pending":
            pending.append(item["id"])
            results.append({"id": item["id"], "status": "pending"})
            continue
        required = ("title", "url", "retrieved_on", "local_path", "sha256", "bytes")
        if any(key not in item for key in required):
            raise ResearchRunError("invalid_case", f"{item['id']} imported metadata is incomplete")
        validate_https_url(str(item["url"]))
        path = root / "evidence" / str(item["local_path"])
        validate_official_file(path, str(item["kind"]))
        if sha256_file(path) != item["sha256"] or path.stat().st_size != item["bytes"]:
            raise ResearchRunError("evidence_drift", f"official evidence changed after import: {item['id']}")
        results.append({"id": item["id"], "status": "imported", "sha256": item["sha256"]})
    return results, pending


def document_audits(path: Path, plan: dict[str, Any], schema: str) -> dict[str, Any]:
    if path.exists() and (path.is_symlink() or not path.is_file()):
        raise ResearchRunError("invalid_document", f"research document must be a regular file: {path.name}")
    if path.is_file() and path.stat().st_size > MAX_DOCUMENT_BYTES:
        raise ResearchRunError("invalid_document", f"research document exceeds the size limit: {path.name}")
    report_result = report_audit.audit_file(path)
    financial_result = financial_rigor.audit_file(path)
    metadata = report_result.get("metadata", {})
    expected = {
        "schema": schema,
        "security": plan["identity"]["security"],
        "thscode": plan["identity"]["thscode"],
        "as_of": plan["as_of"],
        "base_currency": "CNY",
    }
    identity_errors = [f"{key} must match plan.json" for key, value in expected.items() if metadata.get(key) != value]
    if identity_errors:
        report_result = dict(report_result)
        report_result["valid"] = False
        report_result["errors"] = [*report_result.get("errors", []), *identity_errors]
    if schema == "money-craft.thesis.v1" and report_result["valid"] and financial_result["valid"]:
        try:
            research_workflow.load_thesis(path)
        except research_workflow.WorkflowError as exc:
            report_result = dict(report_result)
            report_result["valid"] = False
            report_result["errors"] = [*report_result.get("errors", []), str(exc)]
    return {"report": report_result, "financial": financial_result, "valid": report_result["valid"] and financial_result["valid"]}


def receipt_status(root: Path, plan_sha256: str) -> tuple[bool, str | None]:
    path = root / "completion-receipt.json"
    if not path.is_file() or path.is_symlink():
        return False, None
    receipt = load_json(path)
    if receipt.get("schema") != RECEIPT_SCHEMA or receipt.get("plan_sha256") != plan_sha256:
        return False, "completion receipt identity is invalid"
    bindings = receipt.get("bindings")
    if not isinstance(bindings, dict):
        return False, "completion receipt bindings are missing"
    if set(bindings) != RECEIPT_BOUND_FILES:
        return False, "completion receipt binding allowlist is invalid"
    for name, expected_hash in bindings.items():
        if not isinstance(name, str) or not isinstance(expected_hash, str):
            return False, "completion receipt binding is invalid"
        bound = root / name
        if not bound.is_file() or bound.is_symlink() or sha256_file(bound) != expected_hash:
            return False, f"completion receipt is stale: {name}"
    return True, None


def research_status(workspace: Path | str) -> dict[str, Any]:
    root, plan, case, state = load_workspace(workspace)
    provider_results, provider_pending, provider_gaps = inspect_provider(root, case)
    official_results, official_pending = inspect_official(root, case)
    provider_stage = "pending"
    if len(provider_pending) < len(case["operations"]):
        provider_stage = "incomplete" if provider_pending else ("complete_with_gaps" if provider_gaps else "complete")
    official_stage = "pending" if len(official_pending) == len(case["official_sources"]) else (
        "incomplete" if official_pending else "complete"
    )
    report_checks = document_audits(root / "report.md", plan, "money-craft.report.v1")
    thesis_checks = document_audits(root / "thesis.md", plan, "money-craft.thesis.v1")
    report_stage = "complete" if report_checks["valid"] else "draft"
    thesis_stage = "complete" if thesis_checks["valid"] else "draft"
    plan_sha256 = sha256_file(root / "plan.json")
    receipt_valid, receipt_error = receipt_status(root, plan_sha256)
    manifest_exists = (root / "evidence-manifest.json").is_file()
    ready_for_report = not provider_pending and not official_pending
    complete = (
        receipt_valid
        and ready_for_report
        and report_checks["valid"]
        and thesis_checks["valid"]
        and manifest_exists
    )
    warnings = []
    if provider_gaps:
        warnings.append("provider gaps are declared evidence limitations and must be addressed in the report")
    if receipt_error:
        warnings.append(receipt_error)
    return {
        "schema": STATUS_SCHEMA,
        "valid": True,
        "run_id": state["run_id"],
        "identity": plan["identity"],
        "as_of": plan["as_of"],
        "plan_sha256": plan_sha256,
        "stages": {
            "plan": "complete",
            "provider_evidence": provider_stage,
            "official_evidence": official_stage,
            "report": report_stage,
            "thesis": thesis_stage,
            "audit": "complete" if report_checks["valid"] and thesis_checks["valid"] else "pending",
            "manifest": "complete" if manifest_exists else "pending",
            "receipt": "complete" if receipt_valid else "pending",
        },
        "missing_sources": [*provider_pending, *official_pending],
        "provider_gaps": provider_gaps,
        "provider_results": provider_results,
        "official_results": official_results,
        "ready_for_report": ready_for_report,
        "complete": complete,
        "network_used_by_status": False,
        "warnings": warnings,
    }


def provider_source(root: Path, item: dict[str, Any]) -> dict[str, Any]:
    normalized = root / "evidence" / item["output"]
    payload = normalized_payload(normalized)
    status, _error = operation_status(item, payload, 0 if payload.get("ok") is True else 1)
    files = [
        {
            "role": "normalized-response" if status == "passed" else "normalized-error",
            "path": f"evidence/{item['output']}",
            "sha256": sha256_file(normalized),
        }
    ]
    if status == "passed":
        raw = root / "evidence" / "captures" / item["id"] / "response.json"
        if not raw.is_file() or raw.is_symlink():
            raise ResearchRunError("missing_capture", f"missing captured provider response: {item['id']}")
        files.append(
            {
                "role": "raw-response",
                "path": f"evidence/captures/{item['id']}/response.json",
                "sha256": sha256_file(raw),
            }
        )
    return {
        "id": item["id"],
        "kind": "provider-response",
        "title": item["title"],
        "provider": "fuyao",
        "operation": payload.get("operation"),
        "retrieved_at": payload.get("fetched_at"),
        "status": status,
        "distribution": "private-not-distributed",
        "files": files,
    }


def official_source(root: Path, item: dict[str, Any]) -> dict[str, Any]:
    path = root / "evidence" / item["local_path"]
    role = "downloaded-document" if item["kind"] == "official-document" else "web-snapshot"
    return {
        "id": item["id"],
        "kind": item["kind"],
        "title": item["title"],
        "url": item["url"],
        "retrieved_on": item["retrieved_on"],
        "distribution": "private-not-distributed",
        "files": [{"role": role, "path": f"evidence/{item['local_path']}", "sha256": sha256_file(path)}],
    }


def build_manifest(root: Path, plan: dict[str, Any], case: dict[str, Any]) -> dict[str, Any]:
    sources = [provider_source(root, item) for item in case["operations"]]
    sources.extend(official_source(root, item) for item in case["official_sources"])
    retrieved = [item.get("retrieved_at") for item in sources if isinstance(item.get("retrieved_at"), str)]
    return {
        "schema": MANIFEST_SCHEMA,
        "case_id": plan["identity"]["ticker"],
        "security": plan["identity"]["security"],
        "thscode": plan["identity"]["thscode"],
        "as_of": plan["as_of"],
        "data_cutoff": max(retrieved) if retrieved else None,
        "distribution": {
            "mode": "metadata-only",
            "provider_payloads_distributed": False,
            "downloaded_documents_distributed": False,
            "note": "Only source metadata and SHA-256 bindings may be distributed. Evidence files remain local.",
        },
        "local_evidence": {"default_root": "evidence", "required_for_public_validation": False},
        "provider_documentation": PROVIDER_DOCUMENTATION,
        "source_count": len(sources),
        "sources": sorted(sources, key=lambda item: int(item["id"][1:])),
    }


def finalize_workspace(workspace: Path | str) -> dict[str, Any]:
    root, plan, case, state = load_workspace(workspace)
    status = research_status(root)
    if status["missing_sources"]:
        raise ResearchRunError(
            "incomplete_evidence",
            "cannot finalize while required sources are missing: " + ", ".join(status["missing_sources"]),
        )
    manifest = build_manifest(root, plan, case)
    atomic_json(root / "evidence-manifest.json", manifest)
    report_checks = document_audits(root / "report.md", plan, "money-craft.report.v1")
    thesis_checks = document_audits(root / "thesis.md", plan, "money-craft.thesis.v1")
    audit_payloads = {
        "report-audit.json": report_checks["report"],
        "report-financial-audit.json": report_checks["financial"],
        "thesis-audit.json": thesis_checks["report"],
        "thesis-financial-audit.json": thesis_checks["financial"],
    }
    for name, payload in audit_payloads.items():
        atomic_json(root / name, payload)
    valid = report_checks["valid"] and thesis_checks["valid"]
    receipt_path = root / "completion-receipt.json"
    receipt: dict[str, Any] | None = None
    if valid:
        bindings = {name: sha256_file(root / name) for name in sorted(RECEIPT_BOUND_FILES)}
        candidate = {
            "schema": RECEIPT_SCHEMA,
            "valid": True,
            "run_id": state["run_id"],
            "completed_at": utc_now(),
            "plan_sha256": sha256_file(root / "plan.json"),
            "bindings": bindings,
            "provider_gaps": status["provider_gaps"],
            "automatic_trading": False,
        }
        if receipt_path.exists():
            receipt = load_json(receipt_path)
            comparable = {key: value for key, value in receipt.items() if key != "completed_at"}
            expected = {key: value for key, value in candidate.items() if key != "completed_at"}
            if comparable != expected:
                raise ResearchRunError("finalized_workspace", "completion receipt already binds different artifacts")
        else:
            atomic_json(receipt_path, candidate, replace=False)
            receipt = candidate
            record_event(
                root,
                state,
                "finalized",
                {"manifest_sha256": bindings["evidence-manifest.json"], "provider_gap_count": len(status["provider_gaps"])},
            )
    return {
        "schema": FINALIZE_SCHEMA,
        "valid": valid,
        "run_id": state["run_id"],
        "evidence_manifest": {
            "path": "evidence-manifest.json",
            "sha256": sha256_file(root / "evidence-manifest.json"),
            "source_count": manifest["source_count"],
        },
        "audits": {
            "report": report_checks,
            "thesis": thesis_checks,
        },
        "provider_gaps": status["provider_gaps"],
        "receipt": (
            {"path": "completion-receipt.json", "sha256": sha256_file(receipt_path)} if receipt is not None else None
        ),
        "automatic_trading": False,
    }
