"""Regression tests for the hash-backed publishing handoff inventory."""
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from publishing_handoff import _case_collisions, build_handoff_manifest, write_handoff_manifest_no_clobber


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

    def test_symlinks_are_blocked_without_hashing_the_target(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            project = base / "Book"
            package = project / "PLATFORMS" / "KDP"
            package.mkdir(parents=True)
            outside = base / "private-source.pdf"
            outside.write_bytes(b"external data that is not part of the package")
            link = package / "interior.pdf"
            try:
                link.symlink_to(outside)
            except (OSError, NotImplementedError) as exc:
                self.skipTest(f"symlinks unavailable in this environment: {exc}")
            report = build_handoff_manifest(project, ("KDP",))
            row = report["platforms"]["KDP"]
            self.assertEqual(report["summary"]["symlink_files"], 1)
            self.assertEqual(row["symlink_paths"], ["interior.pdf"])
            self.assertEqual(row["files"], [])
            self.assertTrue(any(action["priority"] == "P0" and "symbolic link" in action["action"]
                                for action in report["actions"]))
            self.assertEqual(outside.read_bytes(), b"external data that is not part of the package")

    def test_handoff_version_includes_symlink_safety(self):
        import publishing_handoff
        self.assertEqual(publishing_handoff.VERSION, "1.1")

    def test_case_insensitive_filename_collisions_are_reported(self):
        # Test the pure path-grouping logic so this passes on Windows (case-insensitive)
        # and Linux/macOS (usually case-sensitive) without filesystem-dependent fixtures.
        collisions = _case_collisions(["Cover.png", "cover.PNG", "interior.pdf"])
        self.assertEqual(collisions, [["Cover.png", "cover.PNG"]])

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
