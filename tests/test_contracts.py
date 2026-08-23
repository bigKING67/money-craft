from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import install_skill  # noqa: E402
import verify_evidence  # noqa: E402


class RepositoryContractTests(unittest.TestCase):
    ACTION_RELEASES = {
        "actions/checkout": ("3d3c42e5aac5ba805825da76410c181273ba90b1", "v7.0.1"),
        "actions/setup-python": ("5fda3b95a4ea91299a34e894583c3862153e4b97", "v7.0.0"),
        "actions/setup-node": ("820762786026740c76f36085b0efc47a31fe5020", "v7.0.0"),
        "actions/upload-artifact": ("043fb46d1a93c77aae656e7c1c64a875d1fc6a0a", "v7.0.1"),
    }

    def test_version_parity(self) -> None:
        version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
        paths = [
            ROOT / "package.json",
            ROOT / ".codex-plugin" / "plugin.json",
            ROOT / ".claude-plugin" / "plugin.json",
            ROOT / ".grok-plugin" / "plugin.json",
        ]
        self.assertEqual((ROOT / "skills" / "money-craft" / "VERSION").read_text(encoding="utf-8").strip(), version)
        for path in paths:
            self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["version"], version)

    def test_pinned_submodule_and_source_targets(self) -> None:
        lock = json.loads((ROOT / "sources.lock.json").read_text(encoding="utf-8"))
        upstream = lock["upstreams"][0]
        completed = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=ROOT / "upstreams" / "ai-berkshire",
            text=True,
            capture_output=True,
            check=True,
        )
        self.assertEqual(completed.stdout.strip(), upstream["pinned_commit"])
        for mapping in upstream["mappings"]:
            self.assertTrue((ROOT / "upstreams" / "ai-berkshire" / mapping["source"]).is_file())
            for target in mapping["targets"]:
                self.assertTrue((ROOT / target).is_file())

    def test_workflow_actions_are_pinned_to_reviewed_node24_releases(self) -> None:
        seen: set[str] = set()
        pattern = re.compile(r"uses:\s+([^@\s]+)@([0-9a-f]{40})\s+#\s+(v[0-9]+\.[0-9]+\.[0-9]+)")
        for path in sorted((ROOT / ".github" / "workflows").glob("*.yml")):
            text = path.read_text(encoding="utf-8")
            all_uses = [line for line in text.splitlines() if "uses:" in line]
            matches = pattern.findall(text)
            self.assertEqual(len(matches), len(all_uses), f"unreviewed mutable action ref in {path.name}")
            for action, revision, version in matches:
                self.assertIn(action, self.ACTION_RELEASES)
                self.assertEqual((revision, version), self.ACTION_RELEASES[action])
                seen.add(action)
        self.assertEqual(seen, set(self.ACTION_RELEASES))

    def test_atomic_installer_and_force_backup(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "skills"
            destination, backup = install_skill.install(root, force=False)
            self.assertIsNone(backup)
            self.assertTrue((destination / "INSTALL_PROVENANCE.json").is_file())
            with self.assertRaises(ValueError):
                install_skill.install(root, force=False)
            destination, backup = install_skill.install(root, force=True)
            self.assertTrue(destination.is_dir())
            self.assertIsNotNone(backup)
            self.assertTrue(backup.is_dir())
            self.assertEqual(backup.parent, root.parent / ".skills-backups")
            self.assertEqual([path.name for path in root.iterdir()], ["money-craft"])

    def test_public_evidence_manifests_are_metadata_only(self) -> None:
        paths = sorted((ROOT / "artifacts" / "acceptance").glob("*/evidence-manifest.json"))
        self.assertTrue(paths)
        for path in paths:
            payload = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(verify_evidence.validate_manifest(payload), [], path.parent.name)
            self.assertFalse(payload["distribution"]["provider_payloads_distributed"])
            self.assertFalse(payload["distribution"]["downloaded_documents_distributed"])


if __name__ == "__main__":
    unittest.main()
