from __future__ import annotations

import json
import os
import re
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = ROOT / "skills" / "money-craft" / "scripts"
TEMPLATE_ROOT = ROOT / "skills" / "money-craft" / "templates"
sys.path.insert(0, str(SCRIPT_DIR))

import tracking_workflow as tracking  # noqa: E402


INITIAL_UPDATE = "| 2026-08-23 | 初始建立 H01 | 初始估值 | 初始结论 | [S01] |"
NEXT_UPDATE = "| 2026-11-01 | H01 转为 WEAKENED | 下调 | 需要复核 | [S02] |"


def thesis_text(
    *,
    as_of: str,
    cutoff: str,
    hypothesis_state: str,
    update_rows: list[str],
) -> str:
    rows = "\n".join(update_rows)
    return f"""---
schema: money-craft.thesis.v1
workflow: thesis
security: Test Company
thscode: 600519.SH
as_of: {as_of}
data_cutoff: {cutoff}
base_currency: CNY
provider_status: unavailable
---
# Test Company 投资论文
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
| R01 | 现金流连续恶化 | fatal | CLEAR | [S02] |
## 更新记录
| 日期 | 假设变化 | 估值变化 | 结论变化 | 来源 |
|---|---|---|---|---|
{rows}
## 来源索引
- [S01] https://example.invalid/annual.pdf
- [S02] https://example.invalid/quarter.pdf
"""


class TrackingWorkflowTests(unittest.TestCase):
    def create_previous(self, root: Path) -> Path:
        previous = root / "previous.md"
        previous.write_text(
            thesis_text(
                as_of="2026-08-23",
                cutoff="2026-08-23T12:00:00+08:00",
                hypothesis_state="UNVERIFIED",
                update_rows=[INITIAL_UPDATE],
            ),
            encoding="utf-8",
        )
        return previous

    def prepare_candidate(self, workspace: Path, *, valid_health: bool = True) -> None:
        (workspace / "thesis.md").write_text(
            thesis_text(
                as_of="2026-11-01",
                cutoff="2026-11-01T12:00:00+08:00",
                hypothesis_state="WEAKENED",
                update_rows=[INITIAL_UPDATE, NEXT_UPDATE],
            ),
            encoding="utf-8",
        )
        card = (workspace / "card.md").read_text(encoding="utf-8")
        (workspace / "card.md").write_text(
            re.sub(r"\{\{[^{}]+\}\}", "已由正式证据复核", card),
            encoding="utf-8",
        )
        state = json.loads((workspace / "state.json").read_text(encoding="utf-8"))
        state["as_of"] = "2026-11-01"
        state["data_cutoff"] = "2026-11-01T12:00:00+08:00"
        state["hypotheses"] = {"H01": "WEAKENED"}
        state["health"] = {
            "score": 9 if valid_health else 10,
            "maximum": 10,
            "status": "WEAKENED",
            "formula": "10 - 1 weakened hypothesis",
        }
        state["next_mandatory_review"] = {
            "event": "下一份正式定期报告",
            "required_workflow": "earnings-review then track init/check",
        }
        (workspace / "state.json").write_text(
            json.dumps(state, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    def test_init_check_status_verify_and_current_resolution(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            previous = self.create_previous(base)
            root = base / "tracking"
            initialized = tracking.initialize_tracking(
                root,
                as_of="2026-11-01",
                previous=previous,
                template_root=TEMPLATE_ROOT,
            )
            workspace = Path(initialized["workspace"])
            self.assertEqual(initialized["schema"], "money-craft.tracking-init.v1")
            self.assertFalse(initialized["execution_boundary"]["network_used"])
            self.assertEqual(stat.S_IMODE((workspace / "run-state.json").stat().st_mode), 0o400)
            self.assertEqual(stat.S_IMODE((workspace / "previous-thesis.md").stat().st_mode), 0o400)

            self.prepare_candidate(workspace)
            sealed = tracking.finalize_tracking(workspace)
            self.assertEqual(sealed["tracking_revision"], "t0001")
            self.assertFalse(workspace.exists())
            revision = root / "revisions" / "t0001"
            self.assertTrue(revision.is_dir())
            self.assertEqual(stat.S_IMODE(revision.stat().st_mode) & 0o222, 0)
            self.assertEqual(stat.S_IMODE((revision / "thesis.md").stat().st_mode) & 0o222, 0)

            status = tracking.tracking_status(root)
            self.assertEqual(status["revisions"], ["t0001"])
            self.assertEqual(status["current"]["tracking_revision"], "t0001")
            verified = tracking.verify_tracking(root)
            self.assertTrue(verified["valid"], verified["errors"])

            next_run = tracking.initialize_tracking(
                root,
                as_of="2026-12-01",
                template_root=TEMPLATE_ROOT,
            )
            next_state = json.loads((Path(next_run["workspace"]) / "run-state.json").read_text(encoding="utf-8"))
            self.assertEqual(next_state["previous"]["path"], str((revision / "thesis.md").resolve()))

    def test_check_rejects_health_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            initialized = tracking.initialize_tracking(
                base / "tracking",
                as_of="2026-11-01",
                previous=self.create_previous(base),
                template_root=TEMPLATE_ROOT,
            )
            workspace = Path(initialized["workspace"])
            self.prepare_candidate(workspace, valid_health=False)
            with self.assertRaisesRegex(tracking.TrackingError, "health"):
                tracking.finalize_tracking(workspace)
            self.assertTrue(workspace.is_dir())

    def test_check_rejects_rewritten_history(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            initialized = tracking.initialize_tracking(
                base / "tracking",
                as_of="2026-11-01",
                previous=self.create_previous(base),
                template_root=TEMPLATE_ROOT,
            )
            workspace = Path(initialized["workspace"])
            self.prepare_candidate(workspace)
            thesis = (workspace / "thesis.md").read_text(encoding="utf-8")
            (workspace / "thesis.md").write_text(
                thesis.replace("初始建立 H01", "改写历史 H01"),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(tracking.TrackingError, "preserved verbatim"):
                tracking.finalize_tracking(workspace)

    def test_verify_detects_writable_or_tampered_revision(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            root = base / "tracking"
            initialized = tracking.initialize_tracking(
                root,
                as_of="2026-11-01",
                previous=self.create_previous(base),
                template_root=TEMPLATE_ROOT,
            )
            workspace = Path(initialized["workspace"])
            self.prepare_candidate(workspace)
            tracking.finalize_tracking(workspace)
            thesis = root / "revisions" / "t0001" / "thesis.md"
            os.chmod(thesis, 0o644)
            verified = tracking.verify_tracking(root)
            self.assertFalse(verified["valid"])
            self.assertTrue(any("writable" in message for message in verified["errors"]))
            thesis.write_text(thesis.read_text(encoding="utf-8") + "\n", encoding="utf-8")
            os.chmod(thesis, 0o444)
            tampered = tracking.verify_tracking(root)
            self.assertFalse(tampered["valid"])
            self.assertTrue(any("mismatch" in message for message in tampered["errors"]))

    def test_init_hash_binds_optional_formal_revision(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            previous = self.create_previous(base)
            formal = base / "r0001"
            formal.mkdir()
            revision_manifest = formal / "REVISION.json"
            revision_manifest.write_text(
                json.dumps(
                    {
                        "schema": "codex.investment-archive-revision.v1",
                        "research_id": "600519-Test Company/2026-08-23",
                        "revision_id": "r0001",
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            initialized = tracking.initialize_tracking(
                base / "tracking",
                as_of="2026-11-01",
                previous=previous,
                source_revision=formal,
                template_root=TEMPLATE_ROOT,
            )
            state = json.loads((Path(initialized["workspace"]) / "state.json").read_text(encoding="utf-8"))
            self.assertEqual(state["source_research"]["revision_id"], "r0001")
            self.assertEqual(
                state["source_research"]["revision_manifest_sha256"],
                tracking.sha256_file(revision_manifest),
            )

    def test_cli_status_and_verify_are_model_free(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            root = base / "tracking"
            previous = self.create_previous(base)
            initialized_command = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT_DIR / "money_craft.py"),
                    "track",
                    "init",
                    "--tracking-root",
                    str(root),
                    "--previous",
                    str(previous),
                    "--as-of",
                    "2026-11-01",
                    "--json",
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(initialized_command.returncode, 0, initialized_command.stdout)
            initialized = json.loads(initialized_command.stdout)
            workspace = Path(initialized["workspace"])
            self.prepare_candidate(workspace)
            checked = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT_DIR / "money_craft.py"),
                    "track",
                    "check",
                    "--workspace",
                    str(workspace),
                    "--json",
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(checked.returncode, 0, checked.stdout)
            self.assertEqual(json.loads(checked.stdout)["tracking_revision"], "t0001")
            for command in ("status", "verify"):
                completed = subprocess.run(
                    [
                        sys.executable,
                        str(SCRIPT_DIR / "money_craft.py"),
                        "track",
                        command,
                        "--tracking-root",
                        str(root),
                        "--json",
                    ],
                    cwd=ROOT,
                    text=True,
                    capture_output=True,
                    check=False,
                )
                self.assertEqual(completed.returncode, 0, completed.stdout)
                payload = json.loads(completed.stdout)
                self.assertTrue(payload["valid"])
                self.assertFalse(payload["network_used"])


if __name__ == "__main__":
    unittest.main()
