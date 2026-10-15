"""Regression tests for the v78-v82 final release integrity bundle."""
import ast
import hashlib
import json
import re
import tempfile
import unittest
import zipfile
from datetime import datetime
from pathlib import Path

FACTORY_PATH = Path(__file__).resolve().parents[1] / "factory.py"
NAMES = (
    "v78_listing_metadata_drift_audit",
    "v79_package_freshness_audit",
    "v80_export_release_handoff_bundle",
    "v81_upload_state_audit",
    "v82_run_release_integrity_center",
)


def load_helpers():
    source = FACTORY_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(FACTORY_PATH))
    functions = {node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)}
    missing = [name for name in NAMES if name not in functions]
    if missing:
        raise AssertionError(f"Missing release integrity helpers: {missing}")
    namespace = {"Path": Path, "json": json, "re": re, "zipfile": zipfile, "datetime": datetime}
    module = ast.Module(body=[functions[name] for name in NAMES], type_ignores=[])
    exec(compile(module, str(FACTORY_PATH), "exec"), namespace)
    return namespace, source


class ReleaseIntegrityBundleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.project = self.root / "book"
        self.project.mkdir()
        self.ns, self.source = load_helpers()
        self.ns.update({
            "FACTORY_VERSION": "97.0",
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

    def test_listing_metadata_drift_blocks_wrong_title_and_author(self):
        (self.project / "project.json").write_text(json.dumps({
            "title": "Correct Title", "author": "J.A.C.", "subtitle": "Horror Coloring",
            "keywords": ["horror", "coloring"]
        }), encoding="utf-8")
        listing_dir = self.project / "MARKETING" / "LISTINGS" / "KDP"
        listing_dir.mkdir(parents=True)
        (listing_dir / "LISTING.json").write_text(json.dumps({
            "platform": "KDP", "fields": {
                "book_title": "Wrong Title", "author": "Wrong Author",
                "subtitle": "Old Subtitle", "keywords": ["other"]
            }
        }), encoding="utf-8")
        result = self.ns["v78_listing_metadata_drift_audit"](self.project)
        self.assertEqual(result["status"], "BLOCKED")
        self.assertTrue(any("title" in error for error in result["errors"]))
        self.assertTrue(any("author" in error for error in result["errors"]))
        self.assertTrue(any("subtitle" in warning for warning in result["warnings"]))

    def test_package_freshness_detects_stale_conventional_interior_pdf(self):
        master = self.project / "MASTER.pdf"
        master.write_bytes(b"current master")
        package = self.project / "PLATFORMS" / "KDP"
        package.mkdir(parents=True)
        (package / "interior.pdf").write_bytes(b"old interior")
        self.ns.update({
            "find_master_pdf": lambda project: master,
            "load_platform_profiles": lambda: {"KDP": {"enabled": True, "output_dir": "KDP"}},
            "v23_verify_package_root": lambda root: {"status": "READY", "errors": [], "warnings": []},
        })
        result = self.ns["v79_package_freshness_audit"](self.project)
        self.assertEqual(result["status"], "NEEDS_REVIEW")
        self.assertEqual(result["platforms"][0]["master_comparison"], "POSSIBLY_STALE")
        self.assertTrue(any("does not match" in warning for warning in result["warnings"]))

    def test_release_bundle_exports_only_after_ready_gates_and_never_overwrites(self):
        package = self.project / "PLATFORMS" / "KDP"
        listing = self.project / "MARKETING" / "LISTINGS" / "KDP"
        package.mkdir(parents=True)
        listing.mkdir(parents=True)
        (package / "interior.pdf").write_bytes(b"interior")
        (listing / "LISTING.json").write_text('{"title":"Book"}', encoding="utf-8")
        readiness = {"overall_status": "READY_TO_UPLOAD", "platforms": [{
            "platform": "KDP", "package_folder": str(package), "listing_folder": str(listing)
        }]}
        drift, freshness, upload = {"status": "PASS"}, {"status": "PASS"}, {"status": "PASS"}
        first = self.ns["v80_export_release_handoff_bundle"](self.project, readiness, drift, freshness, upload)
        second = self.ns["v80_export_release_handoff_bundle"](self.project, readiness, drift, freshness, upload)
        self.assertEqual(first["status"], "EXPORTED")
        self.assertTrue(first["exported"])
        self.assertFalse(first["uploaded"])
        self.assertNotEqual(first["path"], second["path"])
        with zipfile.ZipFile(first["path"], "r") as archive:
            self.assertIn("RELEASE/PLATFORMS/KDP/interior.pdf", archive.namelist())
            self.assertIn("RELEASE_HANDOFF_MANIFEST.json", archive.namelist())
            manifest = json.loads(archive.read("RELEASE_HANDOFF_MANIFEST.json"))
            self.assertTrue(manifest["files"][0]["sha256"])

    def test_release_bundle_is_withheld_when_readiness_needs_review(self):
        result = self.ns["v80_export_release_handoff_bundle"](
            self.project, {"overall_status": "NEEDS_REVIEW", "platforms": []},
            {"status": "PASS"}, {"status": "PASS"}, {"status": "PASS"}
        )
        self.assertEqual(result["status"], "WITHHELD")
        self.assertFalse(result["exported"])

    def test_upload_state_audit_flags_verified_status_without_product_url(self):
        reports = self.project / "REPORTS"
        reports.mkdir()
        (reports / "PLATFORM_UPLOAD_CHECKLIST.json").write_text(json.dumps({
            "platforms": [{"platform": "Gumroad", "manual_status": "PUBLISHED_VERIFIED", "account_product_url": ""}]
        }), encoding="utf-8")
        result = self.ns["v81_upload_state_audit"](self.project, {
            "platforms": [{"platform": "Gumroad", "status": "READY_TO_UPLOAD"}]
        })
        self.assertEqual(result["status"], "NEEDS_REVIEW")
        self.assertTrue(result["uploaded"])
        self.assertTrue(result["published"])
        self.assertTrue(any("no recorded product URL" in warning for warning in result["warnings"]))

    def test_release_center_withholds_export_until_every_gate_passes(self):
        calls = []
        self.ns.update({
            "v61_upload_readiness_board": lambda project: calls.append("readiness") or {"overall_status": "NEEDS_REVIEW", "platforms": []},
            "v78_listing_metadata_drift_audit": lambda project: calls.append("drift") or {"status": "PASS"},
            "v79_package_freshness_audit": lambda project: calls.append("freshness") or {"status": "PASS"},
            "v81_upload_state_audit": lambda project, readiness=None: calls.append("upload") or {"status": "PASS", "uploaded": False, "published": False},
            "v80_export_release_handoff_bundle": lambda *args: calls.append("export") or {"status": "EXPORTED", "exported": True, "path": "release.zip"},
        })
        result = self.ns["v82_run_release_integrity_center"](self.project)
        self.assertEqual(calls, ["readiness", "drift", "freshness", "upload"])
        self.assertEqual(result["status"], "NEEDS_REVIEW")
        self.assertFalse(result["handoff_exported"])

    def test_version_and_menu_wiring(self):
        self.assertIn('FACTORY_VERSION = "113.0"', self.source)
        self.assertIn('27. Final Release Integrity & Handoff Center', self.source)
        self.assertIn('elif c=="27": v82_release_integrity_menu()', self.source)
        tree = ast.parse(self.source)
        for name in NAMES:
            self.assertEqual(sum(1 for node in ast.walk(tree)
                                 if isinstance(node, ast.FunctionDef) and node.name == name), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
