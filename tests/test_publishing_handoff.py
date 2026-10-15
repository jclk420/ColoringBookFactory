"""Regression tests for the hash-backed publishing handoff inventory."""
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from publishing_handoff import build_handoff_manifest, write_handoff_manifest_no_clobber


class PublishingHandoffTests(unittest.TestCase):
    def test_hash_inventory_is_deterministic_and_does_not_change_source(self):
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp) / "Book"
            package = project / "PLATFORMS" / "KDP"
            package.mkdir(parents=True)
            file_path = package / "interior.pdf"
            data = b"%PDF-1.4 sample"
            file_path.write_bytes(data)
            before = file_path.read_bytes()
            report = build_handoff_manifest(project, ("KDP",))
            entry = report["platforms"]["KDP"]["files"][0]
            self.assertEqual(entry["sha256"], hashlib.sha256(data).hexdigest())
            self.assertEqual(file_path.read_bytes(), before)
            self.assertFalse(report["uploaded_or_published"])

    def test_zero_byte_files_are_blocking_actions(self):
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp) / "Book"
            package = project / "PLATFORMS" / "KDP"
            package.mkdir(parents=True)
            (package / "cover.png").write_bytes(b"")
            report = build_handoff_manifest(project, ("KDP",))
            self.assertEqual(report["summary"]["zero_byte_files"], 1)
            self.assertTrue(any(action["action"] == "Package file is empty." for action in report["actions"]))

    def test_case_insensitive_filename_collisions_are_reported(self):
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp) / "Book"
            package = project / "PLATFORMS" / "KDP"
            package.mkdir(parents=True)
            (package / "Cover.png").write_bytes(b"a")
            (package / "cover.PNG").write_bytes(b"b")
            report = build_handoff_manifest(project, ("KDP",))
            self.assertEqual(report["summary"]["case_collisions"], 1)
            self.assertEqual(len(report["platforms"]["KDP"]["case_collisions"]), 1)

    def test_missing_platform_folder_is_reported_without_crashing(self):
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp) / "Book"
            project.mkdir()
            report = build_handoff_manifest(project, ("KDP",))
            self.assertFalse(report["platforms"]["KDP"]["exists"])
            self.assertTrue(any("missing" in item["action"] for item in report["actions"]))

    def test_manifest_writes_unique_reports_without_overwrite(self):
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp) / "Book"
            project.mkdir()
            first = write_handoff_manifest_no_clobber(project, {"run": 1})
            first.write_text('{"preserve": true}\n', encoding="utf-8")
            second = write_handoff_manifest_no_clobber(project, {"run": 2})
            self.assertNotEqual(first, second)
            self.assertEqual(json.loads(first.read_text(encoding="utf-8")), {"preserve": True})
            self.assertEqual(json.loads(second.read_text(encoding="utf-8")), {"run": 2})


if __name__ == "__main__":
    unittest.main(verbosity=2)
