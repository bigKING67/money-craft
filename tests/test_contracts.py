from __future__ import annotations

import json
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

    def test_public_evidence_manifest_is_metadata_only(self) -> None:
        path = ROOT / "artifacts" / "acceptance" / "600519" / "evidence-manifest.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(verify_evidence.validate_manifest(payload), [])
        self.assertFalse(payload["distribution"]["provider_payloads_distributed"])
        self.assertFalse(payload["distribution"]["downloaded_documents_distributed"])


if __name__ == "__main__":
    unittest.main()
