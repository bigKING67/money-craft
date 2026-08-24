#!/usr/bin/env python3
"""Deterministic company-research planning and thesis revision contracts."""

from __future__ import annotations

import datetime as dt
import hashlib
import re
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import financial_rigor
import report_audit

THSCODE_RE = re.compile(r"^\d{6}\.(?:SH|SZ|BJ)$")
REPORT_RE = re.compile(r"^((?:19|20)\d{2})-([1-4])$")
HYPOTHESIS_ID_RE = re.compile(r"^H\d{2,4}$")
RED_LINE_ID_RE = re.compile(r"^R\d{2,4}$")
TABLE_SEPARATOR_RE = re.compile(r"^:?-{3,}:?$")
HYPOTHESIS_COLUMNS = ("ID", "假设", "指标与阈值", "验证来源", "频率", "状态")
RED_LINE_COLUMNS = ("ID", "条件", "严重度", "当前状态", "证据")
UPDATE_COLUMNS = ("日期", "假设变化", "估值变化", "结论变化", "来源")
HYPOTHESIS_STATES = {"SUPPORTED", "WEAKENED", "DAMAGED", "BROKEN", "UNVERIFIED"}
RED_LINE_STATES = {"CLEAR", "WATCH", "TRIGGERED", "UNVERIFIED"}
RED_LINE_SEVERITIES = {"fatal", "material"}
SHANGHAI = ZoneInfo("Asia/Shanghai")


class WorkflowError(RuntimeError):
    def __init__(self, kind: str, message: str, *, exit_code: int = 2) -> None:
        super().__init__(message)
        self.kind = kind
        self.exit_code = exit_code


def parse_date(value: str, label: str) -> dt.date:
    try:
        return dt.date.fromisoformat(value)
    except ValueError as exc:
        raise WorkflowError("invalid_date", f"{label} must be YYYY-MM-DD") from exc


def parse_report_period(value: str) -> tuple[int, int]:
    match = REPORT_RE.fullmatch(value)
    if not match:
        raise WorkflowError("invalid_report_period", "latest report must match YYYY-1 through YYYY-4")
    return int(match.group(1)), int(match.group(2))


def report_period_end(year: int, quarter: int) -> dt.date:
    return {
        1: dt.date(year, 3, 31),
        2: dt.date(year, 6, 30),
        3: dt.date(year, 9, 30),
        4: dt.date(year, 12, 31),
    }[quarter]


def shift_years(value: dt.date, years: int) -> dt.date:
    try:
        return value.replace(year=value.year + years)
    except ValueError:
        return value.replace(year=value.year + years, day=28)


def company_research_plan(
    *,
    security: str,
    thscode: str,
    as_of: str,
    latest_report: str,
    provider: dict[str, Any],
    today: dt.date | None = None,
) -> dict[str, Any]:
    name = security.strip()
    code = thscode.strip().upper()
    if not name or len(name) > 128:
        raise WorkflowError("invalid_identity", "security must be a non-empty name of at most 128 characters")
    if not THSCODE_RE.fullmatch(code):
        raise WorkflowError("invalid_identity", "thscode must be a complete A-share code")
    research_date = parse_date(as_of, "as_of")
    current_date = today or dt.datetime.now(SHANGHAI).date()
    if research_date > current_date:
        raise WorkflowError("future_as_of", "as_of cannot be later than the current Asia/Shanghai date")
    report_year, report_quarter = parse_report_period(latest_report)
    if report_period_end(report_year, report_quarter) > research_date:
        raise WorkflowError("future_report_period", "latest report period ends after as_of")
    annual_report = latest_report if report_quarter == 4 else f"{report_year - 1}-4"
    history_start = shift_years(research_date, -5).isoformat()
    month_start = research_date.replace(day=1).isoformat()
    exchange = {"SH": "SSE", "SZ": "SZSE", "BJ": "BSE"}[code[-2:]]
    comparison_period = f"{report_year - 1}-{report_quarter}"
    reconciliation_checks = ["balance-sheet-equation", "cash-balance-tie"]
    if report_quarter > 1:
        reconciliation_checks.append("quarter-from-ytd")

    operations = [
        {"id": "S01", "operation": "search", "arguments": {"query": code[:6], "limit": 3}},
        {"id": "S02", "operation": "snapshot", "arguments": {"thscodes": code}},
        {"id": "S03", "operation": "valuations", "arguments": {"thscodes": code}},
        {
            "id": "S04",
            "operation": "history",
            "arguments": {
                "thscode": code,
                "start": history_start,
                "end": as_of,
                "interval": "1d",
                "adjust": "forward",
            },
        },
        {
            "id": "S05",
            "operation": "financials",
            "arguments": {"thscode": code, "statement": "income", "period": "annual", "limit": 5},
        },
        {
            "id": "S06",
            "operation": "financials",
            "arguments": {"thscode": code, "statement": "balance", "period": "annual", "limit": 5},
        },
        {
            "id": "S07",
            "operation": "financials",
            "arguments": {"thscode": code, "statement": "cash-flow", "period": "annual", "limit": 5},
        },
        {"id": "S08", "operation": "indicators", "arguments": {"thscode": code, "report": annual_report}},
        {
            "id": "S09",
            "operation": "corporate-actions",
            "arguments": {"thscode": code, "start": history_start, "end": as_of},
        },
        {"id": "S10", "operation": "calendar", "arguments": {"start": month_start, "end": as_of}},
        {
            "id": "S14",
            "operation": "financials",
            "arguments": {"thscode": code, "statement": "income", "period": "quarterly", "limit": 8},
        },
        {
            "id": "S15",
            "operation": "financials",
            "arguments": {"thscode": code, "statement": "balance", "period": "quarterly", "limit": 8},
        },
        {
            "id": "S16",
            "operation": "financials",
            "arguments": {"thscode": code, "statement": "cash-flow", "period": "quarterly", "limit": 8},
        },
    ]
    if latest_report != annual_report:
        operations.append(
            {"id": "S17", "operation": "indicators", "arguments": {"thscode": code, "report": latest_report}}
        )

    return {
        "schema": "money-craft.company-research-plan.v1",
        "mode": "research",
        "identity": {
            "security": name,
            "thscode": code,
            "ticker": code[:6],
            "exchange": exchange,
            "share_class": "A-share",
            "base_currency": "CNY",
        },
        "as_of": as_of,
        "latest_report_period": latest_report,
        "latest_annual_period": annual_report,
        "provider": provider,
        "execution_boundary": {
            "plan_only": True,
            "network_used": False,
            "account_access": False,
            "automatic_trading": False,
        },
        "stages": [
            {"id": "identity", "gate": "exact name and thscode reconciliation"},
            {"id": "official-evidence", "gate": "latest and annual formal filings acquired"},
            {"id": "provider-cross-check", "gate": "bounded operations captured or gaps declared"},
            {"id": "research", "gate": "facts separated from inference and counterevidence retained"},
            {"id": "valuation-and-thesis", "gate": "three scenarios and testable assumptions"},
            {"id": "audit", "gate": "report, financial, and reconciliation audits valid"},
        ],
        "official_evidence_requirements": [
            {"id": "S11", "role": "latest-period formal filing", "period": latest_report, "required": True},
            {"id": "S12", "role": "latest audited annual report", "period": annual_report, "required": True},
            {
                "id": "S13",
                "role": "exchange disclosure or issuer investor-relations index",
                "period": None,
                "required": True,
            },
            {
                "id": "S18",
                "role": "material transaction, subsidiary finance, equity incentive or capital-structure disclosure",
                "period": None,
                "required": False,
                "trigger": "decision-critical subsidiary, governance, dilution, or contingent-obligation fact",
            },
            {
                "id": "S19",
                "role": "official management Q&A or roadshow transcript",
                "period": None,
                "required": False,
                "trigger": "management explanation or an unanswered material question affects the thesis",
            },
            {
                "id": "S20",
                "role": "post-reporting-period material event disclosure",
                "period": None,
                "required": False,
                "trigger": (
                    "financing, listing, acquisition, disposal, repurchase, "
                    "or other material event after period end"
                ),
            },
        ],
        "material_disclosure_contract": {
            "policy": "conditional",
            "index_source_id": "S13",
            "routes": [
                {
                    "source_id": "S18",
                    "source_types": [
                        "material transaction",
                        "subsidiary capital increase",
                        "equity incentive",
                        "capital raising",
                        "related-party transaction",
                    ],
                },
                {
                    "source_id": "S19",
                    "source_types": ["earnings briefing", "roadshow transcript", "official management Q&A"],
                },
                {
                    "source_id": "S20",
                    "source_types": ["post-reporting-period material announcement"],
                },
            ],
            "completion_rule": (
                "Import each triggered optional source; resolve every route in the reconciliation artifact and report."
            ),
        },
        "reconciliation_contract": {
            "schema": "money-craft.financial-reconciliation.v1",
            "path": "financial-reconciliation.json",
            "audit_path": "financial-reconciliation-audit.json",
            "required": True,
            "required_checks": reconciliation_checks,
            "material_disclosure_source_ids": ["S18", "S19", "S20"],
            "period_basis": [
                {"role": "current", "period": latest_report},
                {"role": "comparison", "period": comparison_period},
            ],
        },
        "provider_operations": operations,
        "artifact_contract": {
            "report": {"path": "report.md", "schema": "money-craft.report.v1"},
            "thesis": {"path": "thesis.md", "schema": "money-craft.thesis.v1"},
            "financial_reconciliation": {
                "path": "financial-reconciliation.json",
                "schema": "money-craft.financial-reconciliation.v1",
                "audit_path": "financial-reconciliation-audit.json",
            },
            "evidence_manifest": {
                "path": "evidence-manifest.json",
                "schema": "money-craft.public-evidence-manifest.v1",
                "distribution": "metadata-only",
            },
            "audits": [
                "report-audit.json",
                "report-financial-audit.json",
                "thesis-audit.json",
                "thesis-financial-audit.json",
                "financial-reconciliation-audit.json",
            ],
        },
        "completion_gate": {
            "official_sources_required": True,
            "provider_is_primary_source": False,
            "report_audit_required": True,
            "financial_audit_required": True,
            "financial_reconciliation_required": True,
            "raw_provider_payloads_public": False,
        },
    }


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def split_table_row(line: str) -> list[str]:
    value = line.strip()
    if not value.startswith("|") or not value.endswith("|"):
        return []
    cells = re.split(r"(?<!\\)\|", value[1:-1])
    return [cell.replace(r"\|", "|").strip() for cell in cells]


def parse_table(section: str, columns: tuple[str, ...], label: str) -> list[dict[str, str]]:
    lines = [line for line in section.splitlines() if line.strip().startswith("|")]
    if len(lines) < 2:
        raise WorkflowError("missing_table", f"{label} table is required")
    header = split_table_row(lines[0])
    separator = split_table_row(lines[1])
    if header != list(columns) or len(separator) != len(header) or not all(
        TABLE_SEPARATOR_RE.fullmatch(cell.replace(" ", "")) for cell in separator
    ):
        raise WorkflowError("invalid_table", f"{label} table columns are invalid")
    records: list[dict[str, str]] = []
    for line in lines[2:]:
        values = split_table_row(line)
        if len(values) != len(header):
            raise WorkflowError("invalid_table", f"{label} table row has the wrong number of columns")
        records.append(dict(zip(header, values)))
    if not records:
        raise WorkflowError("empty_table", f"{label} table must contain at least one row")
    return records


def validate_records(
    records: list[dict[str, str]],
    *,
    id_pattern: re.Pattern[str],
    state_column: str,
    states: set[str],
    label: str,
) -> None:
    seen: set[str] = set()
    for record in records:
        record_id = record["ID"]
        if not id_pattern.fullmatch(record_id) or record_id in seen:
            raise WorkflowError("invalid_table_id", f"{label} contains an invalid or duplicate ID: {record_id}")
        seen.add(record_id)
        if record[state_column] not in states:
            raise WorkflowError("invalid_status", f"{record_id} has unsupported status: {record[state_column]}")


def load_thesis(path: Path) -> dict[str, Any]:
    resolved = path.expanduser().resolve()
    if not resolved.is_file():
        raise WorkflowError("missing_thesis", f"thesis does not exist: {path}")
    try:
        text = resolved.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise WorkflowError("invalid_thesis", f"cannot read thesis: {exc}") from exc
    report_result = report_audit.audit_text(text)
    if not report_result["valid"]:
        raise WorkflowError("report_audit_failed", "; ".join(report_result["errors"]))
    financial_result = financial_rigor.audit_text(text)
    if not financial_result["valid"]:
        raise WorkflowError("financial_audit_failed", "; ".join(financial_result["errors"]))
    metadata, body, frontmatter_errors = report_audit.parse_frontmatter(text)
    if frontmatter_errors or metadata.get("schema") != "money-craft.thesis.v1" or metadata.get("workflow") != "thesis":
        raise WorkflowError("invalid_thesis", "document must use money-craft.thesis.v1 with workflow thesis")

    hypotheses = parse_table(
        report_audit.extract_section(body, "核心假设"), HYPOTHESIS_COLUMNS, "核心假设"
    )
    red_lines = parse_table(
        report_audit.extract_section(body, "证伪条件"), RED_LINE_COLUMNS, "证伪条件"
    )
    updates = parse_table(
        report_audit.extract_section(body, "更新记录"), UPDATE_COLUMNS, "更新记录"
    )
    validate_records(
        hypotheses,
        id_pattern=HYPOTHESIS_ID_RE,
        state_column="状态",
        states=HYPOTHESIS_STATES,
        label="核心假设",
    )
    validate_records(
        red_lines,
        id_pattern=RED_LINE_ID_RE,
        state_column="当前状态",
        states=RED_LINE_STATES,
        label="证伪条件",
    )
    for record in red_lines:
        if record["严重度"] not in RED_LINE_SEVERITIES:
            raise WorkflowError("invalid_severity", f"{record['ID']} has unsupported severity: {record['严重度']}")
    update_dates = [parse_date(record["日期"], "update date") for record in updates]
    if update_dates != sorted(update_dates):
        raise WorkflowError("invalid_update_history", "update history dates must be non-decreasing")
    if update_dates[-1] != parse_date(metadata["as_of"], "thesis as_of"):
        raise WorkflowError("update_date_mismatch", "latest update row date must equal thesis as_of")
    source_pairs = report_audit.SOURCE_DEFINITION_RE.findall(
        report_audit.extract_section(body, "来源索引")
    )
    sources = {source_id: target.strip() for source_id, target in source_pairs}
    return {
        "path": resolved,
        "filename": resolved.name,
        "sha256": sha256_text(text),
        "metadata": metadata,
        "body": body,
        "hypotheses": hypotheses,
        "red_lines": red_lines,
        "updates": updates,
        "sources": sources,
        "sections": {
            name: report_audit.extract_section(body, name).strip()
            for name in ("结论", "估值与假设", "风险与反方证据")
        },
        "audits": {
            "report": {"valid": True, "warnings": report_result["warnings"]},
            "financial": {"valid": True, "check_count": len(financial_result["checks"])},
        },
    }


def prepare_thesis_update(previous: Path, *, as_of: str) -> dict[str, Any]:
    snapshot = load_thesis(previous)
    previous_date = parse_date(snapshot["metadata"]["as_of"], "previous as_of")
    next_date = parse_date(as_of, "as_of")
    if next_date < previous_date:
        raise WorkflowError("time_reversal", "new thesis as_of cannot be earlier than the previous version")
    return {
        "schema": "money-craft.thesis-update-plan.v1",
        "identity": {
            "security": snapshot["metadata"]["security"],
            "thscode": snapshot["metadata"]["thscode"],
            "base_currency": snapshot["metadata"]["base_currency"],
        },
        "previous": {
            "filename": snapshot["filename"],
            "sha256": snapshot["sha256"],
            "as_of": snapshot["metadata"]["as_of"],
            "data_cutoff": snapshot["metadata"]["data_cutoff"],
        },
        "target": {
            "as_of": as_of,
            "revision_kind": "same-date-revision" if next_date == previous_date else "periodic-update",
            "required_update_record_date": as_of,
        },
        "hypotheses": snapshot["hypotheses"],
        "red_lines": snapshot["red_lines"],
        "preserved_update_history": snapshot["updates"],
        "existing_source_ids": sorted(snapshot["sources"]),
        "required_actions": [
            "acquire new official evidence before changing factual claims",
            "evaluate every existing hypothesis as SUPPORTED, WEAKENED, DAMAGED, BROKEN, or UNVERIFIED",
            "evaluate every red line as CLEAR, WATCH, TRIGGERED, or UNVERIFIED",
            "preserve all prior update rows verbatim and append exactly one new row",
            "recalculate valuation receipts and run both audits",
        ],
        "completion_gate": {
            "identity_unchanged": True,
            "history_append_only": True,
            "report_audit_required": True,
            "financial_audit_required": True,
        },
        "previous_audits": snapshot["audits"],
    }


def record_diff(
    previous: list[dict[str, str]], current: list[dict[str, str]], *, state_column: str
) -> dict[str, Any]:
    old = {record["ID"]: record for record in previous}
    new = {record["ID"]: record for record in current}
    changed: list[dict[str, Any]] = []
    transitions: list[dict[str, str]] = []
    for record_id in sorted(old.keys() & new.keys()):
        fields = [key for key in old[record_id] if old[record_id][key] != new[record_id][key]]
        if fields:
            changed.append(
                {
                    "id": record_id,
                    "changed_fields": fields,
                    "previous": old[record_id],
                    "current": new[record_id],
                }
            )
        if old[record_id][state_column] != new[record_id][state_column]:
            transitions.append(
                {
                    "id": record_id,
                    "previous": old[record_id][state_column],
                    "current": new[record_id][state_column],
                }
            )
    return {
        "added": [new[record_id] for record_id in sorted(new.keys() - old.keys())],
        "removed": [old[record_id] for record_id in sorted(old.keys() - new.keys())],
        "changed": changed,
        "status_transitions": transitions,
    }


def thesis_diff(previous: Path, current: Path) -> dict[str, Any]:
    old = load_thesis(previous)
    new = load_thesis(current)
    identity_fields = ("security", "thscode", "base_currency")
    for field in identity_fields:
        if old["metadata"].get(field) != new["metadata"].get(field):
            raise WorkflowError("identity_mismatch", f"thesis identity changed: {field}")
    old_date = parse_date(old["metadata"]["as_of"], "previous as_of")
    new_date = parse_date(new["metadata"]["as_of"], "current as_of")
    if new_date < old_date:
        raise WorkflowError("time_reversal", "current thesis as_of is earlier than previous thesis")
    old_cutoff = dt.datetime.fromisoformat(old["metadata"]["data_cutoff"].replace("Z", "+00:00"))
    new_cutoff = dt.datetime.fromisoformat(new["metadata"]["data_cutoff"].replace("Z", "+00:00"))
    if new_cutoff < old_cutoff:
        raise WorkflowError("cutoff_reversal", "current data_cutoff is earlier than previous data_cutoff")
    if new["updates"][: len(old["updates"])] != old["updates"]:
        raise WorkflowError("history_rewrite", "previous update rows must be preserved verbatim")
    appended_updates = new["updates"][len(old["updates"]) :]
    if len(appended_updates) != 1:
        raise WorkflowError("invalid_update_count", "current thesis must append exactly one update row")
    if appended_updates[0]["日期"] != new["metadata"]["as_of"]:
        raise WorkflowError("update_date_mismatch", "new update row date must equal current thesis as_of")

    hypotheses = record_diff(old["hypotheses"], new["hypotheses"], state_column="状态")
    red_lines = record_diff(old["red_lines"], new["red_lines"], state_column="当前状态")
    source_ids = set(old["sources"]) | set(new["sources"])
    source_changes = {
        "added": {key: new["sources"][key] for key in sorted(set(new["sources"]) - set(old["sources"]))},
        "removed": {key: old["sources"][key] for key in sorted(set(old["sources"]) - set(new["sources"]))},
        "changed": {
            key: {"previous": old["sources"][key], "current": new["sources"][key]}
            for key in sorted(source_ids)
            if key in old["sources"]
            and key in new["sources"]
            and old["sources"][key] != new["sources"][key]
        },
    }
    section_changes = {
        name: {
            "changed": old["sections"][name] != new["sections"][name],
            "previous_sha256": sha256_text(old["sections"][name]),
            "current_sha256": sha256_text(new["sections"][name]),
        }
        for name in old["sections"]
    }
    current_hypothesis_states = {record["状态"] for record in new["hypotheses"]}
    current_red_line_states = {record["当前状态"] for record in new["red_lines"]}
    if "BROKEN" in current_hypothesis_states or "TRIGGERED" in current_red_line_states:
        signal = "CRITICAL_REVIEW"
    elif {"DAMAGED", "WEAKENED"} & current_hypothesis_states or "WATCH" in current_red_line_states:
        signal = "REVIEW_REQUIRED"
    elif any(item["changed"] for item in section_changes.values()) or any(
        hypotheses[key] or red_lines[key] for key in ("added", "removed", "changed")
    ):
        signal = "CHANGED"
    else:
        signal = "NO_MATERIAL_CHANGE"
    warnings: list[str] = []
    if hypotheses["removed"]:
        warnings.append("hypotheses were removed; confirm that the new update row explains each removal")
    if red_lines["removed"]:
        warnings.append("red lines were removed; confirm that the new update row explains each removal")
    if source_changes["removed"]:
        warnings.append("source definitions were removed; verify that historical citations remain resolvable")

    return {
        "schema": "money-craft.thesis-diff.v1",
        "valid": True,
        "identity": {field: new["metadata"][field] for field in identity_fields},
        "previous": {
            "filename": old["filename"],
            "sha256": old["sha256"],
            "as_of": old["metadata"]["as_of"],
            "data_cutoff": old["metadata"]["data_cutoff"],
        },
        "current": {
            "filename": new["filename"],
            "sha256": new["sha256"],
            "as_of": new["metadata"]["as_of"],
            "data_cutoff": new["metadata"]["data_cutoff"],
        },
        "signal": signal,
        "hypotheses": hypotheses,
        "red_lines": red_lines,
        "sections": section_changes,
        "sources": source_changes,
        "appended_update": appended_updates[0],
        "audits": {"previous": old["audits"], "current": new["audits"]},
        "warnings": warnings,
    }
