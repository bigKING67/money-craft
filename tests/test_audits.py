from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = ROOT / "skills" / "money-craft" / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

import financial_rigor  # noqa: E402
import financial_reconciliation  # noqa: E402
import report_audit  # noqa: E402


VALID_REPORT = """---
schema: money-craft.report.v1
workflow: research
security: Test Company
thscode: 600519.SH
as_of: 2026-08-23
data_cutoff: 2026-08-23T12:00:00+08:00
base_currency: CNY
provider_status: unavailable
---
# Test Company
## 结论
The evidence is bounded.
## 事实与证据
- 经营现金流同比下降 -1.72% [S01]
- 收入由独立来源复核 [S02]
## 估值与假设
Scenario inputs remain uncertain.
<!-- money-craft-calc: {"id":"C01","operation":"add","inputs":["-1.72","1"],"expected":"-0.72","tolerance":"0.000001"} -->
## 风险与反方证据
The strongest counterargument is retained.
## 证伪条件
Official facts materially change.
## 来源索引
- [S01] https://example.invalid/filing
- [S02] `captures/S02/capture.json`
"""


class ReportAuditTests(unittest.TestCase):
    def test_valid_report_with_negative_number(self) -> None:
        result = report_audit.audit_text(VALID_REPORT)
        self.assertTrue(result["valid"], result["errors"])
        self.assertEqual(result["source_count"], 2)

    def test_unresolved_source_fails(self) -> None:
        text = VALID_REPORT.replace("[S02]", "[S03]", 1)
        result = report_audit.audit_text(text)
        self.assertFalse(result["valid"])
        self.assertTrue(any("unresolved source citation: S03" in error for error in result["errors"]))

    def test_template_placeholder_fails(self) -> None:
        result = report_audit.audit_text(VALID_REPORT.replace("Test Company", "{{security}}", 1))
        self.assertFalse(result["valid"])
        self.assertTrue(any("unresolved template placeholders" in error for error in result["errors"]))

    def test_data_cutoff_requires_timezone(self) -> None:
        result = report_audit.audit_text(
            VALID_REPORT.replace("2026-08-23T12:00:00+08:00", "2026-08-23T12:00:00")
        )
        self.assertFalse(result["valid"])
        self.assertTrue(any("data_cutoff" in error for error in result["errors"]))

    def test_duplicate_source_definition_fails(self) -> None:
        result = report_audit.audit_text(
            VALID_REPORT.replace(
                "- [S02] `captures/S02/capture.json`",
                "- [S01] `captures/S02/capture.json`",
            )
        )
        self.assertFalse(result["valid"])
        self.assertTrue(any("duplicate source definitions" in error for error in result["errors"]))


class FinancialAuditTests(unittest.TestCase):
    def test_exact_negative_receipt(self) -> None:
        result = financial_rigor.audit_text(VALID_REPORT)
        self.assertTrue(result["valid"], result["errors"])
        self.assertEqual(result["checks"][0]["actual"], "-0.72")

    def test_wrong_expected_value_fails(self) -> None:
        result = financial_rigor.audit_text(VALID_REPORT.replace('"expected":"-0.72"', '"expected":"0.72"'))
        self.assertFalse(result["valid"])
        self.assertFalse(result["checks"][0]["passed"])

    def test_weighted_average(self) -> None:
        result = financial_rigor.calculate("weighted_average", ["10", "2", "20", "1"])
        self.assertEqual(result, financial_rigor.decimal_value("13.33333333333333333333333333333333"))


def reconciliation_payload() -> dict[str, object]:
    return {
        "schema": "money-craft.financial-reconciliation.v1",
        "security": "Test Company",
        "thscode": "600519.SH",
        "as_of": "2026-08-23",
        "base_currency": "CNY",
        "required_checks": ["balance-sheet-equation", "cash-balance-tie", "quarter-from-ytd"],
        "period_basis": [
            {
                "role": "current",
                "period": "2026-2",
                "basis": "reported",
                "source_ids": ["S11"],
                "notes": "Current period uses the formal filing.",
            },
            {
                "role": "comparison",
                "period": "2025-2",
                "basis": "restated",
                "source_ids": ["S11", "S12"],
                "notes": "Comparison period uses the restated column.",
            },
        ],
        "restatement_assessment": {
            "status": "restated",
            "source_ids": ["S11", "S12"],
            "notes": "The filing retrospectively restates the comparison period.",
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
                "status": "imported",
                "notes": "A material post-reporting-period financing disclosure was imported.",
            },
        ],
        "checks": [
            {
                "id": "FR01",
                "kind": "balance-sheet-equation",
                "period": "2026-2",
                "unit": "CNY million",
                "inputs": {"assets": "100", "liabilities": "40", "equity": "60"},
                "tolerance": "0.000001",
                "source_ids": ["S11"],
            },
            {
                "id": "FR02",
                "kind": "cash-balance-tie",
                "period": "2026-2",
                "unit": "CNY million",
                "inputs": {"balance_sheet_cash": "25", "cash_flow_ending_cash": "25"},
                "tolerance": "0.000001",
                "source_ids": ["S11"],
            },
            {
                "id": "FR03",
                "kind": "quarter-from-ytd",
                "period": "2026-2",
                "unit": "CNY million",
                "inputs": {"current_ytd": "80", "previous_period_ytd": "30", "reported_quarter": "50"},
                "tolerance": "0.000001",
                "source_ids": ["S11", "S16"],
            },
        ],
        "presentation_to_economics": {
            "status": "items-identified",
            "source_ids": ["S11"],
            "notes": "One non-cash presentation item is material.",
            "items": [
                {
                    "id": "P01",
                    "topic": "Fair-value loss",
                    "accounting_presentation": "Recorded below operating profit.",
                    "operating_interpretation": "Does not represent current-period customer demand.",
                    "cash_effect": "Non-cash in the current period.",
                    "evidence_state": "OBSERVED",
                    "source_ids": ["S11"],
                }
            ],
        },
        "subsequent_events": {
            "status": "identified",
            "source_ids": ["S20"],
            "notes": "A material financing occurred after period end.",
            "items": [
                {
                    "id": "E01",
                    "event": "Convertible financing",
                    "materiality": "May dilute equity holders.",
                    "research_effect": "Update the fully diluted valuation.",
                    "evidence_state": "OBSERVED",
                    "source_ids": ["S20"],
                }
            ],
        },
    }


class FinancialReconciliationTests(unittest.TestCase):
    def test_restatement_and_statement_ties_pass(self) -> None:
        result = financial_reconciliation.audit_payload(reconciliation_payload())
        self.assertTrue(result["valid"], result["errors"])
        self.assertEqual([item["passed"] for item in result["checks"]], [True, True, True])

    def test_mixed_basis_and_failed_cash_tie_are_visible(self) -> None:
        payload = reconciliation_payload()
        payload["period_basis"][1]["basis"] = "unverified"
        payload["checks"][1]["inputs"]["cash_flow_ending_cash"] = "20"
        result = financial_reconciliation.audit_payload(payload)
        self.assertFalse(result["valid"])
        self.assertTrue(any("basis must be resolved" in item for item in result["errors"]))
        self.assertTrue(any("cash-balance-tie does not reconcile" in item for item in result["errors"]))

    def test_research_contract_rejects_unknown_source_and_removed_quarter_check(self) -> None:
        payload = reconciliation_payload()
        payload["checks"][2]["source_ids"] = ["S99"]
        payload["required_checks"] = ["balance-sheet-equation", "cash-balance-tie"]
        contract = {
            "required_checks": ["balance-sheet-equation", "cash-balance-tie", "quarter-from-ytd"],
            "material_disclosure_source_ids": ["S18", "S19", "S20"],
            "period_basis": [
                {"role": "current", "period": "2026-2"},
                {"role": "comparison", "period": "2025-2"},
            ],
        }
        result = financial_reconciliation.audit_payload(
            payload,
            expected_contract=contract,
            allowed_source_ids={"S11", "S12", "S16", "S20"},
        )
        self.assertFalse(result["valid"])
        self.assertTrue(any("required_checks must match plan.json" in item for item in result["errors"]))
        self.assertTrue(any("outside available research evidence" in item for item in result["errors"]))

    def test_comparable_estimate_requires_reproducible_calculation(self) -> None:
        payload = reconciliation_payload()
        payload["period_basis"][1]["basis"] = "comparable-estimate"
        missing = financial_reconciliation.audit_payload(payload)
        self.assertFalse(missing["valid"])
        self.assertTrue(any("calculation is required" in item for item in missing["errors"]))
        payload["period_basis"][1]["calculation"] = {
            "id": "C02",
            "operation": "subtract",
            "inputs": ["100", "10"],
            "expected": "90",
            "tolerance": "0.000001",
        }
        valid = financial_reconciliation.audit_payload(payload)
        self.assertTrue(valid["valid"], valid["errors"])
        self.assertEqual(valid["checks"][0]["kind"], "comparable-estimate")

    def test_cli_audits_reconciliation_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "financial-reconciliation.json"
            path.write_text(json.dumps(reconciliation_payload(), ensure_ascii=False), encoding="utf-8")
            completed = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT_DIR / "money_craft.py"),
                    "audit",
                    "reconciliation",
                    str(path),
                    "--json",
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
        self.assertEqual(completed.returncode, 0, completed.stdout)
        self.assertTrue(json.loads(completed.stdout)["valid"])

    def test_reconciliation_artifact_rejects_secret_like_material(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "financial-reconciliation.json"
            payload = reconciliation_payload()
            payload["restatement_assessment"]["notes"] = "sk-" + "fuyao-" + "abcdefghijklmnop"
            path.write_text(json.dumps(payload), encoding="utf-8")
            result = financial_reconciliation.audit_file(path)
        self.assertFalse(result["valid"])
        self.assertTrue(any("secret-like" in item for item in result["errors"]))


if __name__ == "__main__":
    unittest.main()
