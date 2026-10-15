"""Regression tests for the v88-v92 release evidence history bundle."""
import ast
import hashlib
import json
import re
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

FACTORY_PATH = Path(__file__).resolve().parents[1] / "factory.py"
NAMES = (
    "v88_capture_release_evidence",
    "v89_compare_release_evidence",
    "v90_release_evidence_integrity_audit",
    "v91_release_history_trend",
    "v92_run_release_evidence_center",
)


def load_helpers():
    source = FACTORY_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(FACTORY_PATH))
    functions = {node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)}
    missing = [name for name in NAMES if name not in functions]
    if missing:
        raise AssertionError(f"Missing release evidence helpers: {missing}")
    namespace = {"Path": Path, "json": json, "re": re, "datetime": datetime}
    module = ast.Module(body=[functions[name] for name in NAMES], type_ignores=[])
    exec(compile(module, str(FACTORY_PATH), "exec"), namespace)
    return namespace, source


class ReleaseEvidenceHistoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.project = self.root / "book"
        self.project.mkdir()
        self.ns, self.source = load_helpers()
        self.ns.update({
            "FACTORY_VERSION": "97.0",
            "BOOK_BLUEPRINT_FILENAME": "BOOK_BLUEPRINT.json",
            "PROMPT_MANIFEST_FILENAME": "PROMPT_MANIFEST.json",
            "CREATION_MANIFEST_FILENAME": "CREATION_MANIFEST.json",
            "MARKETING_DIR_NAME": "MARKETING",
            "PLATFORM_DIRNAME": "PLATFORMS",
            "file_hash": lambda path: hashlib.sha256(Path(path).read_bytes()).hexdigest(),
        })

        def load_json(path):
            return json.loads(Path(path).read_text(encoding="utf-8"))

        def save_json(path, data):
            path = Path(path)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(data, indent=2), encoding="utf-8")

        self.ns.update({"load_json": load_json, "save_json": save_json})

    def setup_release_files(self):
        (self.project / "project.json").write_text('{"title":"Evidence Book"}', encoding="utf-8")
        master_dir = self.project / "MASTER"
        master_dir.mkdir()
        master = master_dir / "Evidence Book.pdf"
        master.write_bytes(b"master-pdf")
        package = self.project / "PLATFORMS" / "KDP"
        package.mkdir(parents=True)
        (package / "interior.pdf").write_bytes(b"package-pdf")
        (package / "PACKAGE_MANIFEST.json").write_text('{"files":[]}', encoding="utf-8")
        listing = self.project / "MARKETING" / "LISTINGS" / "KDP"
        listing.mkdir(parents=True)
        (listing / "LISTING.json").write_text('{"platform":"KDP"}', encoding="utf-8")
        return master, package, listing

    def test_capture_snapshot_tracks_master_packages_and_listing_drafts(self):
        master, package, listing = self.setup_release_files()
        self.ns["find_master_pdf"] = lambda project: master
        result = self.ns["v88_capture_release_evidence"](self.project, {"overall_status": "READY_TO_UPLOAD"})
        self.assertEqual(result["status"], "CAPTURED")
        self.assertTrue(Path(result["snapshot_path"]).is_file())
        snapshot = result["snapshot"]
        paths = {row["path"] for row in snapshot["files"]}
        self.assertIn("MASTER/Evidence Book.pdf", paths)
        self.assertIn("PLATFORMS/KDP/interior.pdf", paths)
        self.assertIn("MARKETING/LISTINGS/KDP/LISTING.json", paths)
        self.assertEqual(snapshot["readiness_status"], "READY_TO_UPLOAD")
        self.assertEqual(snapshot["master_sha256"], hashlib.sha256(master.read_bytes()).hexdigest())

    def test_release_diff_detects_changed_package_file(self):
        master, package, listing = self.setup_release_files()
        self.ns["find_master_pdf"] = lambda project: master
        first = self.ns["v88_capture_release_evidence"](self.project, {"overall_status": "READY_TO_UPLOAD"})
        (package / "interior.pdf").write_bytes(b"updated package pdf")
        second = self.ns["v88_capture_release_evidence"](self.project, {"overall_status": "NEEDS_REVIEW"})
        diff = self.ns["v89_compare_release_evidence"](self.project, second["snapshot_path"])
        self.assertEqual(diff["status"], "DIFF_FOUND")
        self.assertTrue(any(row["path"] == "PLATFORMS/KDP/interior.pdf" for row in diff["changed"]))
        self.assertTrue(diff["readiness_changed"])
        self.assertNotEqual(diff["baseline_snapshot"], diff["current_snapshot"])

    def test_integrity_audit_detects_changed_files_and_rejects_unsafe_paths(self):
        master, package, listing = self.setup_release_files()
        self.ns["find_master_pdf"] = lambda project: master
        snapshot = self.ns["v88_capture_release_evidence"](self.project, {"overall_status": "READY_TO_UPLOAD"})
        (package / "interior.pdf").write_bytes(b"changed after snapshot")
        audit = self.ns["v90_release_evidence_integrity_audit"](self.project, snapshot["snapshot_path"])
        self.assertEqual(audit["status"], "NEEDS_REVIEW")
        self.assertTrue(any(row["path"] == "PLATFORMS/KDP/interior.pdf" for row in audit["changed"]))
        unsafe = self.project / "REPORTS" / "RELEASE_HISTORY" / "release_99999999_999999.json"
        unsafe.parent.mkdir(parents=True, exist_ok=True)
        unsafe.write_text(json.dumps({"files": [{"path": "../../outside.txt", "sha256": "x"}]}), encoding="utf-8")
        audit = self.ns["v90_release_evidence_integrity_audit"](self.project, unsafe)
        self.assertEqual(audit["status"], "BLOCKED")
        self.assertTrue(any("Unsafe snapshot path" in error for error in audit["errors"]))

    def test_history_trend_counts_readiness_states(self):
        master, package, listing = self.setup_release_files()
        self.ns["find_master_pdf"] = lambda project: master
        self.ns["v88_capture_release_evidence"](self.project, {"overall_status": "READY_TO_UPLOAD"})
        self.ns["v88_capture_release_evidence"](self.project, {"overall_status": "NEEDS_REVIEW"})
        trend = self.ns["v91_release_history_trend"](self.project)
        self.assertEqual(trend["status"], "PASS")
        self.assertEqual(trend["snapshot_count"], 2)
        self.assertEqual(trend["readiness_counts"]["READY_TO_UPLOAD"], 1)
        self.assertEqual(trend["readiness_counts"]["NEEDS_REVIEW"], 1)

    def test_evidence_center_chains_snapshot_diff_integrity_and_trend(self):
        calls = []
        self.ns.update({
            "v61_upload_readiness_board": lambda project: calls.append("readiness") or {"overall_status": "READY_TO_UPLOAD"},
            "v88_capture_release_evidence": lambda project, readiness=None: calls.append("snapshot") or {"status": "CAPTURED", "snapshot_path": "snap.json", "file_count": 4, "master_sha256": "abc"},
            "v89_compare_release_evidence": lambda project, snapshot_path=None: calls.append("diff") or {"status": "BASELINE_CREATED", "added": [], "changed": [], "removed": []},
            "v90_release_evidence_integrity_audit": lambda project, snapshot_path=None: calls.append("integrity") or {"status": "PASS"},
            "v91_release_history_trend": lambda project: calls.append("trend") or {"status": "PASS"},
        })
        result = self.ns["v92_run_release_evidence_center"](self.project)
        self.assertEqual(calls, ["readiness", "snapshot", "diff", "integrity", "trend"])
        self.assertEqual(result["status"], "CAPTURED")
        self.assertEqual(result["snapshot_file_count"], 4)
        self.assertFalse(result["uploaded"])
        self.assertFalse(result["published"])

    def test_version_and_menu_wiring(self):
        self.assertIn('FACTORY_VERSION = "97.0"', self.source)
        self.assertIn('29. Release Evidence History & Change Tracker', self.source)
        self.assertIn('elif c=="29": v92_release_evidence_menu()', self.source)
        tree = ast.parse(self.source)
        for name in NAMES:
            self.assertEqual(sum(1 for node in ast.walk(tree)
                                 if isinstance(node, ast.FunctionDef) and node.name == name), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
