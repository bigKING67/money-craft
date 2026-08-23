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

import research_workflow as workflow  # noqa: E402


def thesis_text(
    *,
    as_of: str,
    cutoff: str,
    hypothesis_state: str,
    update_rows: list[str],
    security: str = "Test Company",
    thscode: str = "600519.SH",
) -> str:
    rows = "\n".join(update_rows)
    return f"""---
schema: money-craft.thesis.v1
workflow: thesis
security: {security}
thscode: {thscode}
as_of: {as_of}
data_cutoff: {cutoff}
base_currency: CNY
provider_status: unavailable
---
# {security} 投资论文
## 结论
当前结论以正式证据为准。[S01][S02]
## 事实与证据
- 收入由正式报告核验 [S01]
- 现金流由独立来源复核 [S02]
## 核心假设
| ID | 假设 | 指标与阈值 | 验证来源 | 频率 | 状态 |
|---|---|---|---|---|---|
| H01 | 收入质量可持续 | 收入与现金流匹配 | [S01][S02] | 季度 | {hypothesis_state} |
## 估值与假设
情景估值仍需持续验证。[S01]
<!-- money-craft-calc: {{"id":"C01","operation":"multiply","inputs":["2","3"],"expected":"6","tolerance":"0.000001"}} -->
## 风险与反方证据
核心风险是现金流与利润背离。[S02]
## 证伪条件
| ID | 条件 | 严重度 | 当前状态 | 证据 |
|---|---|---|---|---|
| R01 | 现金流连续恶化 | fatal | UNVERIFIED | [S02] |
## 更新记录
| 日期 | 假设变化 | 估值变化 | 结论变化 | 来源 |
|---|---|---|---|---|
{rows}
## 来源索引
- [S01] https://example.invalid/annual.pdf
- [S02] https://example.invalid/quarter.pdf
"""


INITIAL_UPDATE = "| 2026-08-23 | 初始建立 H01 | 初始估值 | 初始结论 | [S01] |"
NEXT_UPDATE = "| 2026-11-01 | H01 转为 WEAKENED | 下调 | 需要复核 | [S02] |"


class CompanyResearchPlanTests(unittest.TestCase):
    def test_plan_is_identity_bound_and_has_complete_operation_matrix(self) -> None:
        plan = workflow.company_research_plan(
            security="美的集团",
            thscode="000333.sz",
            as_of="2026-08-23",
            latest_report="2026-1",
            provider={"mode": "disabled", "configured": False, "network_checked": False},
            today=dt.date(2026, 8, 23),
        )
        self.assertEqual(plan["identity"]["thscode"], "000333.SZ")
        self.assertEqual(plan["identity"]["exchange"], "SZSE")
        self.assertEqual(plan["latest_annual_period"], "2025-4")
        self.assertEqual(
            [item["id"] for item in plan["provider_operations"]],
            ["S01", "S02", "S03", "S04", "S05", "S06", "S07", "S08", "S09", "S10", "S14", "S15", "S16", "S17"],
        )
        self.assertEqual(plan["provider_operations"][3]["arguments"]["start"], "2021-08-23")
        self.assertFalse(plan["execution_boundary"]["network_used"])

    def test_plan_rejects_report_period_after_as_of(self) -> None:
        with self.assertRaisesRegex(workflow.WorkflowError, "ends after as_of"):
            workflow.company_research_plan(
                security="Example",
                thscode="600519.SH",
                as_of="2026-08-23",
                latest_report="2026-3",
                provider={"mode": "disabled", "configured": False, "network_checked": False},
                today=dt.date(2026, 8, 23),
            )

    def test_cli_research_plan_is_model_free_json(self) -> None:
        completed = subprocess.run(
            [
                sys.executable,
                str(SCRIPT_DIR / "money_craft.py"),
                "research",
                "plan",
                "--security",
                "贵州茅台",
                "--thscode",
                "600519.SH",
                "--as-of",
                "2026-08-23",
                "--latest-report",
                "2026-2",
                "--provider-mode",
                "disabled",
                "--json",
            ],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        payload = json.loads(completed.stdout)
        self.assertEqual(payload["schema"], "money-craft.company-research-plan.v1")
        self.assertTrue(payload["execution_boundary"]["plan_only"])

    def test_required_provider_fails_with_workflow_error_when_unconfigured(self) -> None:
        with tempfile.TemporaryDirectory() as home:
            environment = dict(os.environ)
            environment.pop("FUYAO_API_KEY", None)
            environment["HOME"] = home
            completed = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT_DIR / "money_craft.py"),
                    "research",
                    "plan",
                    "--security",
                    "贵州茅台",
                    "--thscode",
                    "600519.SH",
                    "--as-of",
                    "2026-08-23",
                    "--latest-report",
                    "2026-2",
                    "--provider-mode",
                    "required",
                    "--json",
                ],
                cwd=ROOT,
                env=environment,
                text=True,
                capture_output=True,
                check=False,
            )
        self.assertEqual(completed.returncode, 3)
        payload = json.loads(completed.stdout)
        self.assertEqual(payload["schema"], "money-craft.workflow-error.v1")
        self.assertEqual(payload["error"]["kind"], "missing_configuration")


class ThesisWorkflowTests(unittest.TestCase):
    def write(self, directory: Path, name: str, text: str) -> Path:
        path = directory / name
        path.write_text(text, encoding="utf-8")
        return path

    def test_prepare_update_binds_previous_and_requires_append_only_history(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            previous = self.write(
                root,
                "previous.md",
                thesis_text(
                    as_of="2026-08-23",
                    cutoff="2026-08-23T12:00:00+08:00",
                    hypothesis_state="UNVERIFIED",
                    update_rows=[INITIAL_UPDATE],
                ),
            )
            plan = workflow.prepare_thesis_update(previous, as_of="2026-11-01")
            self.assertEqual(plan["schema"], "money-craft.thesis-update-plan.v1")
            self.assertEqual(plan["hypotheses"][0]["ID"], "H01")
            self.assertEqual(plan["target"]["revision_kind"], "periodic-update")
            self.assertEqual(len(plan["previous"]["sha256"]), 64)
            self.assertTrue(plan["previous_audits"]["financial"]["valid"])

    def test_diff_reports_status_transition_and_appended_update(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            previous = self.write(
                root,
                "previous.md",
                thesis_text(
                    as_of="2026-08-23",
                    cutoff="2026-08-23T12:00:00+08:00",
                    hypothesis_state="UNVERIFIED",
                    update_rows=[INITIAL_UPDATE],
                ),
            )
            current = self.write(
                root,
                "current.md",
                thesis_text(
                    as_of="2026-11-01",
                    cutoff="2026-11-01T12:00:00+08:00",
                    hypothesis_state="WEAKENED",
                    update_rows=[INITIAL_UPDATE, NEXT_UPDATE],
                ),
            )
            result = workflow.thesis_diff(previous, current)
            self.assertTrue(result["valid"])
            self.assertEqual(result["signal"], "REVIEW_REQUIRED")
            self.assertEqual(
                result["hypotheses"]["status_transitions"],
                [{"id": "H01", "previous": "UNVERIFIED", "current": "WEAKENED"}],
            )
            self.assertEqual(result["appended_update"]["日期"], "2026-11-01")
            completed = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT_DIR / "money_craft.py"),
                    "thesis",
                    "diff",
                    "--previous",
                    str(previous),
                    "--current",
                    str(current),
                    "--json",
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertEqual(json.loads(completed.stdout)["signal"], "REVIEW_REQUIRED")

    def test_diff_rejects_rewritten_history(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            previous = self.write(
                root,
                "previous.md",
                thesis_text(
                    as_of="2026-08-23",
                    cutoff="2026-08-23T12:00:00+08:00",
                    hypothesis_state="UNVERIFIED",
                    update_rows=[INITIAL_UPDATE],
                ),
            )
            rewritten = INITIAL_UPDATE.replace("初始结论", "改写旧结论")
            current = self.write(
                root,
                "current.md",
                thesis_text(
                    as_of="2026-11-01",
                    cutoff="2026-11-01T12:00:00+08:00",
                    hypothesis_state="WEAKENED",
                    update_rows=[rewritten, NEXT_UPDATE],
                ),
            )
            with self.assertRaisesRegex(workflow.WorkflowError, "preserved verbatim"):
                workflow.thesis_diff(previous, current)

    def test_prepare_rejects_thesis_without_current_update_row(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            previous = self.write(
                root,
                "previous.md",
                thesis_text(
                    as_of="2026-08-24",
                    cutoff="2026-08-24T12:00:00+08:00",
                    hypothesis_state="UNVERIFIED",
                    update_rows=[INITIAL_UPDATE],
                ),
            )
            with self.assertRaisesRegex(workflow.WorkflowError, "latest update row date"):
                workflow.prepare_thesis_update(previous, as_of="2026-11-01")

    def test_diff_rejects_security_identity_change(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            previous = self.write(
                root,
                "previous.md",
                thesis_text(
                    as_of="2026-08-23",
                    cutoff="2026-08-23T12:00:00+08:00",
                    hypothesis_state="UNVERIFIED",
                    update_rows=[INITIAL_UPDATE],
                ),
            )
            current = self.write(
                root,
                "current.md",
                thesis_text(
                    as_of="2026-11-01",
                    cutoff="2026-11-01T12:00:00+08:00",
                    hypothesis_state="WEAKENED",
                    update_rows=[INITIAL_UPDATE, NEXT_UPDATE],
                    security="Another Company",
                ),
            )
            with self.assertRaisesRegex(workflow.WorkflowError, "identity changed"):
                workflow.thesis_diff(previous, current)


if __name__ == "__main__":
    unittest.main()
