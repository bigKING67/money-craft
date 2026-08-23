from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = ROOT / "skills" / "money-craft" / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

import financial_rigor  # noqa: E402
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


if __name__ == "__main__":
    unittest.main()
