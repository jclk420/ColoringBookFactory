"""The completion audit must honor status and warnings recorded by package generators."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from publishing_completion import _verify_platform_manifest


class ManifestReadinessStatusTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.package = self.root / "PLATFORMS" / "Sample"
        self.package.mkdir(parents=True)
        self.master = self.root / "MASTER.pdf"
        self.master.write_bytes(b"master-pdf")
        self.interior = self.package / "interior.pdf"
        self.interior.write_bytes(b"interior-pdf")
        self.master_hash = hashlib.sha256(self.master.read_bytes()).hexdigest()
        self.interior_hash = hashlib.sha256(self.interior.read_bytes()).hexdigest()

    def write_manifest(self, status, warnings=None):
        payload = {
            "schema_version": 5,
            "status": status,
            "files": ["interior.pdf"],
            "file_hashes": {"interior.pdf": self.interior_hash},
            "master_sha256": self.master_hash,
            "warnings": warnings or [],
        }
        (self.package / "PACKAGE_MANIFEST.json").write_text(
            json.dumps(payload), encoding="utf-8"
        )

    def test_blocked_manifest_cannot_pass_integrity_as_ready(self):
        self.write_manifest("BLOCKED")
        result = _verify_platform_manifest(self.package, self.master_hash)
        self.assertEqual(result["status"], "BLOCKED")
        self.assertTrue(any("declares non-ready status: BLOCKED" in error for error in result["errors"]))

    def test_ready_with_warnings_manifest_requires_review_and_propagates_warning(self):
        self.write_manifest("READY_WITH_WARNINGS", ["Cover should be reviewed."])
        result = _verify_platform_manifest(self.package, self.master_hash)
        self.assertEqual(result["status"], "NEEDS_REVIEW")
        self.assertTrue(any("declares review status: READY_WITH_WARNINGS" in warning for warning in result["warnings"]))
        self.assertTrue(any("Cover should be reviewed." in warning for warning in result["warnings"]))

    def test_ready_manifest_with_matching_hashes_passes(self):
        self.write_manifest("READY")
        result = _verify_platform_manifest(self.package, self.master_hash)
        self.assertEqual(result["status"], "READY")
        self.assertFalse(result["errors"])
        self.assertFalse(result["warnings"])

    def test_unknown_legacy_status_requires_review(self):
        self.write_manifest("CUSTOM_STATUS")
        result = _verify_platform_manifest(self.package, self.master_hash)
        self.assertEqual(result["status"], "NEEDS_REVIEW")
        self.assertTrue(any("no recognized readiness status" in warning for warning in result["warnings"]))


if __name__ == "__main__":
    unittest.main()
