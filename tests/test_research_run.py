from __future__ import annotations

import datetime as dt
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = ROOT / "skills" / "money-craft" / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

import research_run  # noqa: E402
from research_workflow import company_research_plan  # noqa: E402


def example_plan(*, provider_mode: str = "auto") -> dict[str, object]:
    return company_research_plan(
        security="美的集团",
        thscode="000333.SZ",
        as_of="2026-08-23",
        latest_report="2026-1",
        provider={
            "mode": provider_mode,
            "configured": provider_mode != "disabled",
            "configuration_source": "secure-file" if provider_mode != "disabled" else None,
            "network_checked": False,
        },
        today=dt.date(2026, 8, 23),
    )


class FakeProviderRunner:
    def __init__(self, *, gap_source_id: str | None = None) -> None:
        self.gap_source_id = gap_source_id
        self.commands: list[list[str]] = []

    def __call__(self, command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        self.commands.append(command)
        source_id = command[command.index("--source-id") + 1]
        capture_root = Path(command[command.index("--capture-dir") + 1])
        operation = command[command.index("data") + 1]
        actual_operation = operation
        if operation == "financials":
            statement = command[command.index("--statement") + 1]
            actual_operation = f"financials.{statement}"
        if source_id == self.gap_source_id:
            payload = {
                "schema": "money-craft.data-response.v1",
                "ok": False,
                "provider": "fuyao",
                "operation": actual_operation,
                "request_id": "fixture-gap",
                "fetched_at": "2026-08-23T12:00:00Z",
                "source_timestamp_ms": None,
                "parameters": {},
                "data": None,
                "warnings": [],
                "error": {"kind": "data_error", "code": 3001, "message": "fixture gap", "retryable": False},
            }
            return subprocess.CompletedProcess(command, 4, json.dumps(payload, ensure_ascii=False), "")
        data: dict[str, object] = {}
        if operation == "search":
            data = {"item": [{"name": "美的集团", "thscode": "000333.SZ"}]}
        capture = capture_root / source_id
        capture.mkdir(parents=True)
        (capture / "response.json").write_text(
            json.dumps({"code": 0, "message": "ok", "request_id": f"fixture-{source_id}", "data": data}),
            encoding="utf-8",
        )
        payload = {
            "schema": "money-craft.data-response.v1",
            "ok": True,
            "provider": "fuyao",
            "operation": actual_operation,
            "request_id": f"fixture-{source_id}",
            "fetched_at": f"2026-08-23T12:{int(source_id[1:]):02d}:00Z",
            "source_timestamp_ms": None,
            "parameters": {},
            "data": data,
            "warnings": [],
            "capture": {"source_id": source_id, "path": str(capture)},
        }
        return subprocess.CompletedProcess(command, 0, json.dumps(payload, ensure_ascii=False), "")


def valid_report(schema: str, workflow: str) -> str:
    extra = ""
    if schema == "money-craft.thesis.v1":
        extra = """
## 核心假设

| ID | 假设 | 指标与阈值 | 验证来源 | 频率 | 状态 |
|---|---|---|---|---|---|
| H01 | 收入质量可持续 | 收入与现金流匹配 | [S01][S11] | 季度 | UNVERIFIED |
"""
    red_line = "事实发生重大变化。"
    update = ""
    if schema == "money-craft.thesis.v1":
        red_line = """| ID | 条件 | 严重度 | 当前状态 | 证据 |
|---|---|---|---|---|
| R01 | 现金流连续恶化 | fatal | UNVERIFIED | [S01][S11] |"""
        update = """
## 更新记录

| 日期 | 假设变化 | 估值变化 | 结论变化 | 来源 |
|---|---|---|---|---|
| 2026-08-23 | 初始建立 | 初始建立 | 初始建立 | [S01][S11] |
"""
    return f"""---
schema: {schema}
workflow: {workflow}
security: 美的集团
thscode: 000333.SZ
as_of: 2026-08-23
data_cutoff: 2026-08-23T12:17:00+00:00
base_currency: CNY
provider_status: configured
---
# 美的集团
## 结论
证据边界明确。
## 事实与证据
- 公司身份已经核验 [S01]
- 正式报告已经导入 [S11]
{extra}
## 重大披露与期后事项
已按条件路由核对重大披露与期后事项 [S11]
## 重述口径与三表勾稽
口径和三表勾稽结果记录在结构化回执中 [S11]
## 估值与假设
情景输入仍需持续复核。
<!-- money-craft-calc: {{"id":"C01","operation":"add","inputs":["1","2"],"expected":"3"}} -->
## 风险与反方证据
结构化数据可能存在缺口。
## 证伪条件
{red_line}
{update}
## 来源索引
- [S01] `evidence/S01-search.normalized.json`
- [S11] `evidence/S11-official.pdf`
"""


def valid_reconciliation() -> dict[str, object]:
    return {
        "schema": "money-craft.financial-reconciliation.v1",
        "security": "美的集团",
        "thscode": "000333.SZ",
        "as_of": "2026-08-23",
        "base_currency": "CNY",
        "required_checks": ["balance-sheet-equation", "cash-balance-tie"],
        "period_basis": [
            {
                "role": "current",
                "period": "2026-1",
                "basis": "reported",
                "source_ids": ["S11"],
                "notes": "Current period formal filing.",
            },
            {
                "role": "comparison",
                "period": "2025-1",
                "basis": "reported",
                "source_ids": ["S11", "S12"],
                "notes": "Comparison period reported column.",
            },
        ],
        "restatement_assessment": {
            "status": "none-disclosed",
            "source_ids": ["S11", "S12"],
            "notes": "No retrospective restatement was disclosed in the inspected filings.",
        },
        "material_disclosure_assessment": [
            {
                "source_id": "S18",
                "status": "not-triggered",
                "notes": "No decision-critical transaction or capital-structure trigger was identified.",
            },
            {
                "source_id": "S19",
                "status": "not-triggered",
                "notes": "Management Q&A was not required for a decision-critical claim.",
            },
            {
                "source_id": "S20",
                "status": "not-triggered",
                "notes": "No decision-critical post-reporting-period event trigger was identified.",
            },
        ],
        "checks": [
            {
                "id": "FR01",
                "kind": "balance-sheet-equation",
                "period": "2026-1",
                "unit": "CNY million",
                "inputs": {"assets": "100", "liabilities": "40", "equity": "60"},
                "tolerance": "0.000001",
                "source_ids": ["S11"],
            },
            {
                "id": "FR02",
                "kind": "cash-balance-tie",
                "period": "2026-1",
                "unit": "CNY million",
                "inputs": {"balance_sheet_cash": "25", "cash_flow_ending_cash": "25"},
                "tolerance": "0.000001",
                "source_ids": ["S11"],
            },
        ],
        "presentation_to_economics": {
            "status": "no-material-distortion",
            "source_ids": ["S11"],
            "notes": "No decision-critical accounting presentation distortion was identified.",
            "items": [],
        },
        "subsequent_events": {
            "status": "none-disclosed",
            "source_ids": ["S11", "S13"],
            "notes": "No material post-reporting-period event was identified through the official index.",
            "items": [],
        },
    }


class ResearchRunTests(unittest.TestCase):
    def test_global_workspace_declares_unconfigured_yfinance_and_keeps_official_evidence_primary(self) -> None:
        plan = company_research_plan(
            security="NVIDIA Corporation",
            security_id="US-NASDAQ:NVDA",
            base_currency="USD",
            as_of="2026-08-23",
            latest_report="2026-2",
            latest_report_end="2025-07-27",
            latest_annual_report="2025-4",
            provider={"mode": "auto", "configured": False, "network_checked": False},
            today=dt.date(2026, 8, 23),
        )
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory) / "run"
            initialized = research_run.initialize_workspace(
                workspace,
                plan,
                template_root=ROOT / "skills" / "money-craft" / "templates",
            )
            self.assertEqual(initialized["provider_operation_count"], 0)
            case = json.loads((workspace / "case.json").read_text(encoding="utf-8"))
            self.assertEqual(case["operations"], [])
            report = (workspace / "report.md").read_text(encoding="utf-8")
            self.assertIn("security_id: US-NASDAQ:NVDA", report)
            self.assertIn("base_currency: USD", report)
            status = research_run.research_status(workspace)
            self.assertEqual(status["stages"]["provider_evidence"], "not_applicable")
            self.assertEqual(status["provider_gaps"], ["provider:yfinance:not-configured"])
            self.assertEqual(status["missing_sources"], ["S11", "S12", "S13"])

    def initialize(self, directory: str, *, provider_mode: str = "auto") -> Path:
        workspace = Path(directory) / "run"
        result = research_run.initialize_workspace(
            workspace,
            example_plan(provider_mode=provider_mode),
            template_root=ROOT / "skills" / "money-craft" / "templates",
        )
        self.assertTrue(result["valid"])
        self.assertFalse(result["network_used"])
        return workspace

    def collect(self, workspace: Path, *, gap_source_id: str | None = None) -> FakeProviderRunner:
        runner = FakeProviderRunner(gap_source_id=gap_source_id)
        research_run.collect_workspace(workspace, runtime=Path("fixture-runtime.py"), runner=runner)
        return runner

    def import_official_sources(self, workspace: Path, directory: str) -> None:
        source_root = Path(directory) / "official"
        source_root.mkdir()
        sources = (
            ("S11", b"%PDF-1.7\nq1"),
            ("S12", b"%PDF-1.7\nannual"),
            ("S13", b"<!doctype html><html></html>"),
        )
        for source_id, payload in sources:
            source = source_root / source_id
            source.write_bytes(payload)
            result = research_run.import_official_source(
                workspace,
                source_id=source_id,
                source_file=source,
                url=f"https://example.invalid/{source_id}",
                retrieved_on="2026-08-23",
            )
            self.assertTrue(result["valid"])

    def test_init_derives_single_case_truth_and_rejects_plan_drift(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = self.initialize(directory)
            plan = json.loads((workspace / "plan.json").read_text(encoding="utf-8"))
            case = json.loads((workspace / "case.json").read_text(encoding="utf-8"))
            self.assertEqual(
                [(item["id"], item["operation"], item["arguments"]) for item in case["operations"]],
                [(item["id"], item["operation"], item["arguments"]) for item in plan["provider_operations"]],
            )
            self.assertEqual(len(case["operations"]), 14)
            self.assertEqual(
                [item["id"] for item in case["official_sources"]],
                ["S11", "S12", "S13", "S18", "S19", "S20"],
            )
            self.assertTrue((workspace / "financial-reconciliation.json").is_file())
            self.assertEqual(
                [item["id"] for item in case["official_sources"] if item.get("required", True)],
                ["S11", "S12", "S13"],
            )
            with self.assertRaisesRegex(research_run.ResearchRunError, "already exists"):
                self.initialize(directory)
            plan["as_of"] = "2026-08-22"
            (workspace / "plan.json").write_text(json.dumps(plan), encoding="utf-8")
            with self.assertRaisesRegex(research_run.ResearchRunError, "plan.json changed"):
                research_run.research_status(workspace)

    def test_default_workspace_uses_money_archive_research_layer(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            plan = example_plan()
            plan["identity"]["security"] = " 美的/集团 "
            workspace, run_id = research_run.allocate_default_workspace(
                plan,
                root=Path(directory) / "money",
            )
            self.assertEqual(
                workspace,
                (Path(directory) / "money").resolve()
                / "000333-美的-集团"
                / "2026-08-23"
                / ".research"
                / run_id,
            )
            result = research_run.initialize_workspace(
                workspace,
                plan,
                template_root=ROOT / "skills" / "money-craft" / "templates",
                run_id=run_id,
            )
            self.assertEqual(result["run_id"], run_id)
            state = json.loads((workspace / "run-state.json").read_text(encoding="utf-8"))
            self.assertEqual(state["run_id"], run_id)

    def test_output_root_precedence_is_explicit_environment_then_default(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            explicit, explicit_source = research_run.output_root(
                base / "explicit",
                environment={research_run.OUTPUT_ROOT_ENV: str(base / "environment")},
                home=base / "home",
            )
            configured, configured_source = research_run.output_root(
                environment={research_run.OUTPUT_ROOT_ENV: str(base / "environment")},
                home=base / "home",
            )
            default, default_source = research_run.output_root(environment={}, home=base / "home")
            self.assertEqual((explicit, explicit_source), ((base / "explicit").resolve(), "command-line"))
            self.assertEqual(
                (configured, configured_source),
                ((base / "environment").resolve(), f"environment:{research_run.OUTPUT_ROOT_ENV}"),
            )
            self.assertEqual(
                (default, default_source),
                ((base / "home" / "Documents" / "sixseven" / "money").resolve(), "default"),
            )

    def test_collect_is_non_overwriting_and_resume_is_model_free(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = self.initialize(directory)
            runner = self.collect(workspace)
            self.assertEqual(len(runner.commands), 14)
            status = research_run.research_status(workspace)
            self.assertEqual(status["stages"]["provider_evidence"], "complete")
            self.assertEqual(status["missing_sources"], ["S11", "S12", "S13"])
            with self.assertRaisesRegex(research_run.ResearchRunError, "already exists"):
                research_run.collect_workspace(workspace, runtime=Path("fixture-runtime.py"), runner=runner)
            before = len(runner.commands)
            resumed = research_run.collect_workspace(
                workspace,
                runtime=Path("fixture-runtime.py"),
                resume=True,
                runner=runner,
            )
            self.assertTrue(resumed["valid"])
            self.assertEqual(resumed["network_requests_attempted"], 0)
            self.assertEqual(len(runner.commands), before)
            self.assertTrue(all(item["resumed"] for item in resumed["results"]))

    def test_provider_gap_is_visible_and_never_reported_as_valid(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = self.initialize(directory)
            result = research_run.collect_workspace(
                workspace,
                runtime=Path("fixture-runtime.py"),
                runner=FakeProviderRunner(gap_source_id="S03"),
            )
            self.assertFalse(result["valid"])
            self.assertTrue(result["complete"])
            self.assertEqual(result["provider_gaps"], 1)
            status = research_run.research_status(workspace)
            self.assertEqual(status["stages"]["provider_evidence"], "complete_with_gaps")
            self.assertEqual(status["provider_gaps"], ["S03"])
            self.assertFalse(status["complete"])

    def test_official_import_is_hash_bound_and_non_overwriting(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = self.initialize(directory)
            source = Path(directory) / "official.pdf"
            source.write_bytes(b"%PDF-1.7\nfixture")
            result = research_run.import_official_source(
                workspace,
                source_id="S11",
                source_file=source,
                url="https://example.invalid/report.pdf",
                retrieved_on="2026-08-23",
            )
            self.assertEqual(result["sha256"], research_run.sha256_file(workspace / "evidence" / "S11-official.pdf"))
            with self.assertRaisesRegex(research_run.ResearchRunError, "already imported"):
                research_run.import_official_source(
                    workspace,
                    source_id="S11",
                    source_file=source,
                    url="https://example.invalid/report.pdf",
                )
            (workspace / "evidence" / "S11-official.pdf").write_bytes(b"%PDF-1.7\ntampered")
            with self.assertRaisesRegex(research_run.ResearchRunError, "changed after import"):
                research_run.research_status(workspace)

    def test_finalize_binds_manifest_audits_and_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = self.initialize(directory)
            self.collect(workspace)
            self.import_official_sources(workspace, directory)
            (workspace / "report.md").write_text(
                valid_report("money-craft.report.v1", "research"), encoding="utf-8"
            )
            (workspace / "thesis.md").write_text(
                valid_report("money-craft.thesis.v1", "thesis"), encoding="utf-8"
            )
            (workspace / "financial-reconciliation.json").write_text(
                json.dumps(valid_reconciliation(), ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            result = research_run.finalize_workspace(workspace)
            self.assertTrue(result["valid"], result["audits"])
            self.assertEqual(result["evidence_manifest"]["source_count"], 17)
            self.assertTrue(result["audits"]["financial_reconciliation"]["valid"])
            self.assertIsNotNone(result["receipt"])
            receipt = json.loads((workspace / "completion-receipt.json").read_text(encoding="utf-8"))
            self.assertEqual(len(receipt["bindings"]), 11)
            self.assertIn("financial-reconciliation.json", receipt["bindings"])
            self.assertIn("financial-reconciliation-audit.json", receipt["bindings"])
            status = research_run.research_status(workspace)
            self.assertTrue(status["complete"])
            self.assertTrue(research_run.finalize_workspace(workspace)["valid"])
            (workspace / "report.md").write_text(
                valid_report("money-craft.report.v1", "research") + "\n",
                encoding="utf-8",
            )
            stale = research_run.research_status(workspace)
            self.assertFalse(stale["complete"])
            self.assertTrue(any("stale" in warning for warning in stale["warnings"]))

    def test_finalize_fails_closed_while_reconciliation_is_unverified(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = self.initialize(directory)
            self.collect(workspace)
            self.import_official_sources(workspace, directory)
            (workspace / "report.md").write_text(
                valid_report("money-craft.report.v1", "research"), encoding="utf-8"
            )
            (workspace / "thesis.md").write_text(
                valid_report("money-craft.thesis.v1", "thesis"), encoding="utf-8"
            )
            result = research_run.finalize_workspace(workspace)
            self.assertFalse(result["valid"])
            self.assertFalse(result["audits"]["financial_reconciliation"]["valid"])
            self.assertIsNone(result["receipt"])
            self.assertFalse((workspace / "completion-receipt.json").exists())

    def test_research_report_requires_source_bound_disclosure_and_reconciliation_sections(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "report.md"
            text = valid_report("money-craft.report.v1", "research")
            text = text.replace(
                "## 重大披露与期后事项\n已按条件路由核对重大披露与期后事项 [S11]\n",
                "",
            )
            path.write_text(text, encoding="utf-8")
            checks = research_run.document_audits(path, example_plan(), "money-craft.report.v1")
            self.assertFalse(checks["valid"])
            self.assertTrue(
                any("重大披露与期后事项" in item for item in checks["report"]["errors"]),
                checks["report"]["errors"],
            )

    def test_optional_material_disclosure_can_be_imported_without_blocking_default_flow(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = self.initialize(directory)
            status = research_run.research_status(workspace)
            optional = {item["id"]: item for item in status["official_results"] if not item["required"]}
            self.assertEqual(set(optional), {"S18", "S19", "S20"})
            self.assertTrue(all(item["status"] == "optional-not-imported" for item in optional.values()))
            source = Path(directory) / "material.html"
            source.write_text("<!doctype html><html><body>fixture</body></html>", encoding="utf-8")
            imported = research_run.import_official_source(
                workspace,
                source_id="S18",
                source_file=source,
                url="https://example.invalid/material-event",
                retrieved_on="2026-08-23",
            )
            self.assertEqual(imported["kind"], "official-material")
            self.assertTrue(imported["local_path"].endswith(".html"))
            self.collect(workspace)
            self.import_official_sources(workspace, directory)
            (workspace / "report.md").write_text(
                valid_report("money-craft.report.v1", "research"), encoding="utf-8"
            )
            (workspace / "thesis.md").write_text(
                valid_report("money-craft.thesis.v1", "thesis"), encoding="utf-8"
            )
            optional_reconciliation = valid_reconciliation()
            optional_reconciliation["material_disclosure_assessment"][0]["status"] = "imported"
            optional_reconciliation["material_disclosure_assessment"][0]["notes"] = (
                "A decision-critical material transaction disclosure was imported."
            )
            (workspace / "financial-reconciliation.json").write_text(
                json.dumps(optional_reconciliation, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            finalized = research_run.finalize_workspace(workspace)
            self.assertTrue(finalized["valid"])
            self.assertEqual(finalized["evidence_manifest"]["source_count"], 18)
            manifest = json.loads((workspace / "evidence-manifest.json").read_text(encoding="utf-8"))
            optional_source = next(item for item in manifest["sources"] if item["id"] == "S18")
            self.assertEqual(optional_source["kind"], "official-material")

    def test_cli_disabled_provider_fails_before_collection(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory) / "cli-run"
            runtime = ROOT / "skills" / "money-craft" / "scripts" / "money_craft.py"
            init = subprocess.run(
                [
                    sys.executable,
                    str(runtime),
                    "research",
                    "init",
                    "--security",
                    "美的集团",
                    "--thscode",
                    "000333.SZ",
                    "--as-of",
                    "2026-08-23",
                    "--latest-report",
                    "2026-1",
                    "--provider-mode",
                    "disabled",
                    "--workspace",
                    str(workspace),
                    "--json",
                ],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(init.returncode, 0, init.stdout)
            environment = dict(os.environ)
            environment.pop("FUYAO_API_KEY", None)
            collect = subprocess.run(
                [sys.executable, str(runtime), "research", "collect", "--workspace", str(workspace), "--json"],
                text=True,
                capture_output=True,
                check=False,
                env=environment,
            )
            payload = json.loads(collect.stdout)
            self.assertEqual(collect.returncode, 2)
            self.assertEqual(payload["error"]["kind"], "provider_disabled")
            self.assertEqual(list((workspace / "evidence").glob("*.normalized.json")), [])

    def test_cli_init_without_workspace_uses_configured_output_root(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output_root = Path(directory) / "money"
            runtime = ROOT / "skills" / "money-craft" / "scripts" / "money_craft.py"
            environment = dict(os.environ)
            environment[research_run.OUTPUT_ROOT_ENV] = str(output_root)
            initialized = subprocess.run(
                [
                    sys.executable,
                    str(runtime),
                    "research",
                    "init",
                    "--security",
                    "美的集团",
                    "--thscode",
                    "000333.SZ",
                    "--as-of",
                    "2026-08-23",
                    "--latest-report",
                    "2026-1",
                    "--provider-mode",
                    "disabled",
                    "--json",
                ],
                text=True,
                capture_output=True,
                check=False,
                env=environment,
            )
            self.assertEqual(initialized.returncode, 0, initialized.stdout)
            payload = json.loads(initialized.stdout)
            workspace = Path(payload["workspace"])
            self.assertEqual(workspace.parent.name, ".research")
            self.assertEqual(workspace.parent.parent.name, "2026-08-23")
            self.assertEqual(workspace.parent.parent.parent.name, "000333-美的集团")
            self.assertEqual(workspace.name, payload["run_id"])
            self.assertTrue((workspace / "plan.json").is_file())


if __name__ == "__main__":
    unittest.main()
