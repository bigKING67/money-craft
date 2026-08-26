from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = ROOT / "skills" / "money-craft" / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

import money_craft  # noqa: E402
import report_renderer  # noqa: E402

try:  # 渲染端到端用例需要可选 Markdown 包；核心运行时保持 stdlib-only
    import markdown  # noqa: F401

    HAS_MARKDOWN = True
except ImportError:
    HAS_MARKDOWN = False


SAMPLE_REPORT = """> 研究日期：2026-08-24
> 数据截止：2026-08-23T23:59:59+08:00
> 核心结论：长期质量较高，当前结论为 WATCH。

<style>body { font-size: 9pt; }</style>

# 示例公司（600000.SH）基本面研究

> 研究对象：示例公司

## 结论

截止日收盘价为 84.30 元，按2025年基本每股收益计算的静态 PE 约 14.53 倍。[S01]

## 财务趋势

| 指标 | 2021 | 2022 | 2023 | 2024 | 2025 |
|---|---:|---:|---:|---:|---:|
| 营业收入（亿元） | 100 | 110 | 120 | 130 | 150 |
| 归母净利润（亿元） | 10 | 11 | 13 | 15 | 18 |
| 经营现金流（亿元） | 8 | 13 | 9 | 16 | 14 |

## 估值与假设

| 情景 | EPS | PE | 示意价值 |
|---|---:|---:|---:|
| Bear | 5.50 | 11 | 60.50 元 |
| Base | 6.09 | 14 | 85.26 元 |
| Bull | 6.50 | 17 | 110.50 元 |

## 主要数据来源

- [S01] https://example.invalid/report.pdf
"""


EXTENDED_REPORT = """> 研究日期：2026-08-24
> 数据截止：2026-08-23T23:59:59+08:00
> 核心结论：长期质量较高，当前结论为 WATCH。

# 示例公司（600000.SH）基本面研究

> 研究对象：示例公司

## 结论

截止日收盘价为 84.30 元，按2025年基本每股收益计算的静态 PE 约 14.53 倍。[S01]

## 财务趋势

| 指标 | 2021 | 2022 | 2023 | 2024 | 2025 |
|---|---:|---:|---:|---:|---:|
| 营业收入（亿元） | 100 | 110 | 120 | 130 | 150 |
| 归母净利润（亿元） | 10 | 11 | 13 | 15 | 18 |
| 基本 EPS（元） | 0.98 | 1.06 | 1.24 | 1.42 | 1.70 |
| 经营现金流（亿元） | 8 | 13 | 9 | 16 | 14 |
| 资本开支代理项（亿元） | 5 | 7 | 6 | 9 | 10 |

## 最近一期变化

| 指标 | 2026Q1 | 同比 |
|---|---:|---:|
| 营业收入（亿元） | 40 | +9.50% |
| 归母净利润（亿元） | 4 | -12.30% |
| 经营现金流（亿元） | 2 | 持平 |
| 基本 EPS（元） | 0.38 | -11.20% |

## 估值与假设

| 情景 | EPS | PE | 示意价值 |
|---|---:|---:|---:|
| Bear | 5.50 | 11 | 60.50 元 |
| Base | 6.09 | 14 | 85.26 元 |
| Bull | 6.50 | 17 | 110.50 元 |

## 风险与证伪条件

| 编号 | 条件 | 强度 | 状态 |
|---|---|---|---|
| R01 | 经营现金流连续两年为负 | material | WATCH |
| R02 | 商誉减值超过净资产三成 | fatal | CLEAR |
| R03 | 关联交易占比异常上升 | material | UNVERIFIED |

## 主要数据来源

- [S01] https://example.invalid/report.pdf
"""


class ReportRendererTests(unittest.TestCase):
    def test_parse_removes_legacy_style_and_preamble(self) -> None:
        parsed = report_renderer.parse_report(SAMPLE_REPORT)
        self.assertEqual(parsed.title, "示例公司（600000.SH）基本面研究")
        self.assertNotIn("<style>", parsed.markdown_body)
        self.assertTrue(parsed.markdown_body.startswith("## 结论"))
        self.assertEqual(report_renderer.report_verdict(parsed), "WATCH")
        self.assertEqual(report_renderer.report_identity(parsed), "600000.SH")
        self.assertEqual(report_renderer.print_identity(parsed), "600000.SH · 2026-08-24")

    def test_metric_extraction_keeps_time_bounded_values(self) -> None:
        parsed = report_renderer.parse_report(SAMPLE_REPORT)
        metrics = report_renderer.metric_items(parsed)
        self.assertEqual(metrics[0]["value"], "84.30 元")
        self.assertEqual(metrics[1]["value"], "14.53×")
        self.assertEqual(metrics[2]["value"], "待复核")

    def test_financial_and_scenario_charts_are_deterministic_inline_svg(self) -> None:
        parsed = report_renderer.parse_report(SAMPLE_REPORT)
        tables = report_renderer.parse_markdown_tables(parsed.markdown_body)
        financial = report_renderer.financial_chart(report_renderer.financial_trend_table(tables))
        scenario = report_renderer.scenario_chart(
            report_renderer.scenario_table(tables), report_renderer.current_price(parsed)
        )
        self.assertIn("<svg", financial)
        self.assertIn("各指标独立量程", financial)
        self.assertIn('class="chart-ring ring-revenue"', financial)
        self.assertIn("归母净利润", financial)
        self.assertIn("经营现金流", financial)
        self.assertNotIn("基本每股收益", financial)
        self.assertNotIn("资本开支代理项", financial)
        self.assertIn("现价 84.30", scenario)
        self.assertNotIn("<script", financial + scenario)

        chinese = SAMPLE_REPORT.replace("| Bear |", "| 悲观 |").replace(
            "| Base |", "| 中性 |"
        ).replace("| Bull |", "| 乐观 |")
        chinese_tables = report_renderer.parse_markdown_tables(
            report_renderer.parse_report(chinese).markdown_body
        )
        self.assertIsNotNone(report_renderer.scenario_table(chinese_tables))

    def test_source_urls_remain_visible_but_not_navigable(self) -> None:
        rendered = report_renderer.decorate_text_nodes(
            '<p>[S01] https://example.invalid/report.pdf?a=1&amp;b=2</p>'
        )
        self.assertIn('class="source-ref"', rendered)
        self.assertIn('data-source-url="https://example.invalid/report.pdf?a=1&amp;b=2"', rendered)
        self.assertNotIn("&amp;amp;", rendered)
        self.assertNotIn('href="https://', rendered)

    def test_source_heading_receives_source_index_semantics(self) -> None:
        rendered, headings = report_renderer.decorate_headings(
            '<h2 id="sources">主要数据来源</h2><ul><li>[S01] source</li></ul>'
        )
        self.assertEqual(headings, [("sources", "主要数据来源")])
        self.assertIn('data-section-kind="sources"', rendered)

    def test_portable_html_verifier_rejects_external_dependencies(self) -> None:
        source_hash = "a" * 64
        valid = (
            '<!doctype html><html><head><meta name="offline-portable" content="true">'
            '<meta name="generator" content="Money Craft">'
            f'<meta name="money-craft-source-sha256" content="{source_hash}"></head>'
            '<body><nav></nav><main><article><span data-source-url="https://example.invalid">'
            "source</span></article></main></body></html>"
        )
        self.assertTrue(report_renderer.verify_html_text(valid, source_sha256=source_hash)["valid"])
        invalid = valid.replace("<nav>", '<nav><a href="https://example.invalid">external</a>')
        result = report_renderer.verify_html_text(invalid, source_sha256=source_hash)
        self.assertFalse(result["valid"])
        self.assertEqual(result["external_dependency_count"], 1)

    def test_money_craft_cli_exposes_report_render_and_verify(self) -> None:
        parser = money_craft.build_parser()
        render = parser.parse_args(["report", "render", "--source", "report.md", "--html-only"])
        verify = parser.parse_args(
            ["report", "verify", "--source", "report.md", "--html", "report.html"]
        )
        self.assertEqual(render.report_command, "render")
        self.assertEqual(verify.report_command, "verify")

    def test_render_outputs_must_be_explicit(self) -> None:
        source = Path("/tmp/canonical/report.md")
        with self.assertRaises(report_renderer.ReportRenderError):
            report_renderer.resolve_output_paths(
                source,
                output_dir=None,
                output_html=None,
                output_pdf=None,
                html_only=False,
            )
        html_path, pdf_path = report_renderer.resolve_output_paths(
            source,
            output_dir=Path("/tmp/rendition"),
            output_html=None,
            output_pdf=None,
            html_only=False,
        )
        self.assertEqual(html_path, Path("/tmp/rendition/report.html").resolve())
        self.assertEqual(pdf_path, Path("/tmp/rendition/report.pdf").resolve())
        self.assertNotIn("kami", html_path.name.lower())
        self.assertNotIn("kami", pdf_path.name.lower())

    def test_current_theme_contract_is_editorial_publication(self) -> None:
        self.assertEqual(report_renderer.CANONICAL_THEME, "editorial-ivory")
        self.assertEqual(report_renderer.LAYOUT_MODE, "research-publication")

    def test_reading_typography_uses_full_column_cjk_and_no_shell_shadow(self) -> None:
        css = report_renderer.DEFAULT_STYLE.read_text(encoding="utf-8")
        self.assertNotIn("68ch", css)
        self.assertNotIn("--measure", css)
        self.assertIn("line-break: strict", css)
        self.assertIn("word-break: keep-all", css)
        self.assertNotIn("box-shadow: 0", css)
        self.assertNotIn("backdrop-filter", css)
        print_block = css[css.index("@media print") :]
        self.assertIn("flex-direction: column", print_block)
        self.assertIn(".report-article {\n    order: 3;", print_block)
        self.assertIn(".visual-extended {\n    order: 4;", print_block)

    def test_audit_seal_uses_reader_chinese(self) -> None:
        parsed = report_renderer.parse_report(SAMPLE_REPORT)
        seal = report_renderer.build_audit_seal(
            "a" * 64,
            {"valid": True, "verdict": "PASS", "pass_count": 10, "total": 10},
            {"summary": {"captured": 15, "expected": 15, "failed": 0}},
            {"revision_id": "r0002", "offline_verifier": {"ok": True, "verified_offline": True}},
            None,
        )
        self.assertIn("报告审计", seal)
        self.assertIn("证据覆盖", seal)
        self.assertIn("离线核验", seal)
        self.assertIn("源文哈希", seal)
        self.assertIn("10/10 通过", seal)
        self.assertIn("15/15，完整", seal)
        self.assertIn("通过", seal)
        self.assertNotIn("FAIL 0", seal)
        self.assertNotIn("Report audit", seal)
        self.assertIn("本阅读层绑定版本 r0002", seal)
        masthead = report_renderer.build_masthead(parsed, {"revision_id": "r0002"})
        self.assertIn('class="print-identity"', masthead)
        self.assertIn("600000.SH · 2026-08-24", masthead)

    def test_extended_charts_derive_only_from_disclosed_tables(self) -> None:
        parsed = report_renderer.parse_report(EXTENDED_REPORT)
        tables = report_renderer.parse_markdown_tables(parsed.markdown_body)

        found = report_renderer.yoy_change_table(tables)
        self.assertIsNotNone(found)
        quality_table, value_index = found
        quality = report_renderer.earnings_quality_chart(quality_table, value_index)
        self.assertIn("chart-yoy-pos", quality)
        self.assertIn("chart-yoy-neg", quality)
        self.assertIn("−12.30%", quality)
        self.assertNotIn("经营现金流", quality)  # 「持平」行不绘制

        primary = report_renderer.financial_chart(
            report_renderer.financial_trend_table(tables)
        )
        self.assertIn("营业收入", primary)
        self.assertIn("归母净利润", primary)
        self.assertIn("经营现金流", primary)
        self.assertNotIn("基本每股收益", primary)
        self.assertNotIn("资本开支代理项", primary)
        self.assertEqual(primary.count('class="chart-ring'), 3)

        cash_flow = report_renderer.cash_flow_structure_chart(
            report_renderer.financial_trend_table(tables)
        )
        self.assertIn("chart-fcf", cash_flow)
        self.assertIn("ring-fcf", cash_flow)
        self.assertIn("ring-operating-cash", cash_flow)
        self.assertIn("evidence-state", cash_flow)  # INFERRED 属性以状态徽章呈现
        self.assertIn("INFERRED", cash_flow)
        # FCF 代理 = 经营 − 开支：2025 年 14 - 10 = 4，必须出现在派生序列 title 中
        self.assertIn("FCF 代理 2025 4", cash_flow)

        rows = report_renderer.falsification_rows(tables)
        self.assertEqual(
            rows,
            [("R01", "material", "WATCH"), ("R02", "fatal", "CLEAR"), ("R03", "material", "UNVERIFIED")],
        )
        falsification = report_renderer.falsification_status_chart(rows)
        self.assertIn('data-severity="fatal"', falsification)
        self.assertIn("WATCH 1 / CLEAR 1 / UNVERIFIED 1", falsification)

        evidence = {
            "groups": [
                {"source_id": "s02", "title": "公司公告", "items": [1]},
                {"source_id": "s01", "title": "年度报告", "items": [1, 2, 3]},
            ]
        }
        coverage = report_renderer.evidence_coverage_chart(evidence)
        self.assertLess(coverage.index("S01"), coverage.index("S02"))
        self.assertIsNone(report_renderer.evidence_coverage_chart(None))
        self.assertIsNone(report_renderer.evidence_coverage_chart({"groups": []}))

        # 缺输入时静默降级：基础样例无同比表、无资本开支行，相关图表不得生成
        bare_tables = report_renderer.parse_markdown_tables(
            report_renderer.parse_report(SAMPLE_REPORT).markdown_body
        )
        self.assertIsNone(report_renderer.yoy_change_table(bare_tables))
        self.assertIsNone(
            report_renderer.cash_flow_structure_chart(
                report_renderer.financial_trend_table(bare_tables)
            )
        )

    @unittest.skipUnless(HAS_MARKDOWN, "optional markdown package unavailable")
    def test_build_document_splits_primary_and_extended_views(self) -> None:
        parsed = report_renderer.parse_report(EXTENDED_REPORT)
        document, chart_count = report_renderer.build_document(
            parsed,
            "a" * 64,
            template=report_renderer.DEFAULT_TEMPLATE.read_text(encoding="utf-8"),
            style="",
            script="",
            audit=None,
            evidence=None,
            revision=None,
            archive_manifest=None,
            charts=True,
        )
        self.assertEqual(chart_count, 5)  # 无 evidence manifest 时证据覆盖组件降级
        summary_start = document.index('<section class="visual-summary"')
        extended_start = document.index('<section class="visual-extended"')
        # 模板结构：<main> 先开，两个视图 section 均嵌在 main 内、正文 article 之前
        main_start = document.index('<main id="report-content"')
        main_end = document.index("</main>")
        self.assertLess(main_start, summary_start)
        self.assertLess(summary_start, extended_start)
        self.assertLess(extended_start, main_end)
        primary = document[summary_start:extended_start]
        extended = document[extended_start:main_end]
        self.assertEqual(primary.count("<figure"), 2)
        self.assertIn("financial-trends", primary)
        self.assertIn("valuation-scenarios", primary)
        self.assertEqual(extended.count("<figure"), 3)

    @unittest.skipUnless(HAS_MARKDOWN, "optional markdown package unavailable")
    def test_primary_view_never_absorbs_extended_charts_when_trend_table_missing(self) -> None:
        # 缺财务趋势表时主视图降级为仅估值情景；扩展图表不得漂移进主视图
        head, rest = EXTENDED_REPORT.split("## 最近一期变化", 1)
        trendless_source = head.split("## 财务趋势")[0] + "## 最近一期变化" + rest
        parsed = report_renderer.parse_report(trendless_source)
        document, _ = report_renderer.build_document(
            parsed,
            "a" * 64,
            template=report_renderer.DEFAULT_TEMPLATE.read_text(encoding="utf-8"),
            style="",
            script="",
            audit=None,
            evidence=None,
            revision=None,
            archive_manifest=None,
            charts=True,
        )
        summary_start = document.index('<section class="visual-summary"')
        extended_start = document.index('<section class="visual-extended"')
        primary = document[summary_start:extended_start]
        extended = document[extended_start:]
        self.assertEqual(primary.count("<figure"), 1)
        self.assertIn('data-chart="valuation-scenarios"', primary)
        self.assertNotIn('data-chart="earnings-quality"', primary)
        self.assertIn('data-chart="earnings-quality"', extended)

    def test_chart_palette_tokens_match_css_contract(self) -> None:
        css = report_renderer.DEFAULT_STYLE.read_text(encoding="utf-8")

        def tokens(section: str) -> dict[str, str]:
            if section == "dark":
                start = css.index(':root[data-theme="dark"] {')
            elif section == "print":
                start = css.index("@media print {")
                start = css.index(":root,", start)
            else:
                start = css.index(":root {")
            block = css[start : css.index("}", start)]
            return dict(re.findall(r"(--chart-[a-z-]+):\s*(#[0-9A-Fa-f]{6})", block))

        light_expected = {
            "--chart-revenue": report_renderer.CHART_SERIES_LIGHT["revenue"],
            "--chart-net-profit": report_renderer.CHART_SERIES_LIGHT["net_profit"],
            "--chart-eps": report_renderer.CHART_SERIES_LIGHT["eps"],
            "--chart-operating-cash": report_renderer.CHART_SERIES_LIGHT["operating_cash"],
            "--chart-capex-proxy": report_renderer.CHART_SERIES_LIGHT["capex_proxy"],
            "--chart-scenario": report_renderer.SCENARIO_BAR_LIGHT,
            "--chart-up": report_renderer.SCENARIO_BAR_LIGHT,
            "--chart-down": report_renderer.CHART_SERIES_LIGHT["revenue"],
        }
        dark_expected = {
            "--chart-revenue": report_renderer.CHART_SERIES_DARK["revenue"],
            "--chart-net-profit": report_renderer.CHART_SERIES_DARK["net_profit"],
            "--chart-eps": report_renderer.CHART_SERIES_DARK["eps"],
            "--chart-operating-cash": report_renderer.CHART_SERIES_DARK["operating_cash"],
            "--chart-capex-proxy": report_renderer.CHART_SERIES_DARK["capex_proxy"],
            "--chart-scenario": report_renderer.SCENARIO_BAR_DARK,
            "--chart-up": report_renderer.SCENARIO_BAR_DARK,
            "--chart-down": report_renderer.CHART_SERIES_DARK["revenue"],
        }
        self.assertEqual(tokens("light"), light_expected)
        self.assertEqual(tokens("dark"), dark_expected)
        # 打印强制白纸：显式回到 light 值，阻断暗色模式值泄漏进 PDF
        self.assertEqual(tokens("print"), light_expected)


if __name__ == "__main__":
    unittest.main()
