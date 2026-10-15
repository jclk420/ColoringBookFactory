"""Regression tests for the v63-v67 five-stage publishing workflow."""
import ast
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

FACTORY_PATH = Path(__file__).resolve().parents[1] / "factory.py"
NAMES = (
    "v63_source_pdf_integrity_audit",
    "v64_platform_upload_checklist",
    "v65_release_action_plan",
    "v66_release_delivery_map",
    "v67_run_publishing_workflow",
)


def load_helpers():
    source = FACTORY_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(FACTORY_PATH))
    functions = {node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)}
    missing = [name for name in NAMES if name not in functions]
    if missing:
        raise AssertionError(f"Missing publishing workflow helpers: {missing}")
    namespace = {"Path": Path, "json": json, "datetime": __import__("datetime").datetime}
    module = ast.Module(body=[functions[name] for name in NAMES], type_ignores=[])
    exec(compile(module, str(FACTORY_PATH), "exec"), namespace)
    return namespace, source, functions


class PublishingWorkflowBundleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.project = self.root / "book"
        self.project.mkdir()
        self.ns, self.source, self.functions = load_helpers()
        self.saved = {}

        def load_json(path):
            return json.loads(Path(path).read_text(encoding="utf-8"))

        def save_json(path, data):
            path = Path(path)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(data, indent=2), encoding="utf-8")
            self.saved[str(path)] = data

        self.ns.update({
            "FACTORY_VERSION": "97.0",
            "MARKETING_DIR_NAME": "MARKETING",
            "load_json": load_json,
            "save_json": save_json,
            "file_hash": lambda path: hashlib.sha256(Path(path).read_bytes()).hexdigest(),
        })

    def test_source_pdf_audit_verifies_digest_and_detects_changed_source(self):
        source = self.root / "source.pdf"
        source.write_bytes(b"source-a")
        digest = hashlib.sha256(source.read_bytes()).hexdigest()
        (self.project / "project.json").write_text(json.dumps({
            "source_pdf": str(source), "source_pdf_sha256": digest
        }), encoding="utf-8")
        audit = self.ns["v63_source_pdf_integrity_audit"](self.project)
        self.assertEqual(audit["status"], "VERIFIED")
        source.write_bytes(b"source-b")
        audit = self.ns["v63_source_pdf_integrity_audit"](self.project)
        self.assertEqual(audit["status"], "SOURCE_CHANGED")
        self.assertTrue(audit["read_only"])

    def test_upload_checklist_preserves_manual_status_and_defaults_new_platform(self):
        reports = self.project / "REPORTS"
        reports.mkdir()
        (reports / "PLATFORM_UPLOAD_CHECKLIST.json").write_text(json.dumps({
            "platforms": [{"platform": "KDP", "manual_status": "UPLOADED_VERIFIED",
                           "account_product_url": "https://example.invalid/product"}]
        }), encoding="utf-8")
        result = self.ns["v64_platform_upload_checklist"](self.project, {
            "platforms": [
                {"platform": "KDP", "status": "READY_TO_UPLOAD", "package_folder": "KDP", "listing_folder": "KDP-L"},
                {"platform": "Gumroad", "status": "NEEDS_REVIEW", "package_folder": "G", "listing_folder": "G-L"},
            ]
        })
        rows = {row["platform"]: row for row in result["platforms"]}
        self.assertEqual(rows["KDP"]["manual_status"], "UPLOADED_VERIFIED")
        self.assertEqual(rows["Gumroad"]["manual_status"], "NOT_UPLOADED")
        self.assertTrue(rows["KDP"]["uploaded"])
        self.assertFalse(rows["Gumroad"]["uploaded"])
        self.assertFalse(rows["Gumroad"]["published"])

    def test_action_plan_prioritizes_blockers_and_includes_provenance_review(self):
        plan = self.ns["v65_release_action_plan"](self.project, {
            "overall_status": "BLOCKED",
            "platforms": [{"platform": "KDP", "status": "BLOCKED",
                           "blockers": ["Manifest hash mismatch"], "warnings": ["Check subtitle"]}]
        }, {"status": "SOURCE_CHANGED", "message": "Digest changed", "report_path": "source-report.json"})
        self.assertEqual(plan["priority_counts"]["P0"], 2)
        self.assertEqual(plan["priority_counts"]["P1"], 2)
        self.assertEqual(plan["tasks"][0]["priority"], "P0")
        self.assertTrue(any("provenance" in row["action"].lower() for row in plan["tasks"]))

    def test_delivery_map_lists_exact_package_and_listing_files(self):
        package = self.project / "PLATFORMS" / "KDP"
        listing = self.project / "MARKETING" / "LISTINGS" / "KDP"
        package.mkdir(parents=True)
        listing.mkdir(parents=True)
        (package / "book.pdf").write_bytes(b"pdf")
        (listing / "LISTING.txt").write_text("draft", encoding="utf-8")
        report = self.ns["v66_release_delivery_map"](self.project, {"platforms": [{
            "platform": "KDP", "status": "READY_TO_UPLOAD",
            "package_folder": str(package), "listing_folder": str(listing)
        }]})
        row = report["platforms"][0]
        self.assertTrue(row["package_exists"])
        self.assertTrue(row["listing_exists"])
        self.assertEqual(row["package_files"][0]["relative_path"].replace(chr(92), "/"), "PLATFORMS/KDP/book.pdf")
        self.assertEqual(row["listing_files"][0]["relative_path"].replace(chr(92), "/"), "MARKETING/LISTINGS/KDP/LISTING.txt")

    def test_delivery_map_refuses_to_inventory_paths_outside_project(self):
        outside = self.root / "outside"
        outside.mkdir()
        secret = outside / "private.txt"
        secret.write_text("not part of the project", encoding="utf-8")
        report = self.ns["v66_release_delivery_map"](self.project, {"platforms": [{
            "platform": "KDP", "status": "NEEDS_REVIEW",
            "package_folder": str(outside), "listing_folder": str(outside)
        }]})
        row = report["platforms"][0]
        self.assertFalse(row["package_exists"])
        self.assertFalse(row["listing_exists"])
        self.assertEqual(row["package_files"], [])
        self.assertEqual(row["listing_files"], [])

    def test_one_click_orchestrator_preserves_drafts_and_does_not_rebuild_master(self):
        calls = []
        readiness = {"overall_status": "NEEDS_REVIEW", "platforms": []}
        self.ns.update({
            "v22_build_all_platform_listings": lambda project, overwrite_existing=False: (
                calls.append(("listing", overwrite_existing)) or {"status": "OK"}
            ),
            "v61_upload_readiness_board": lambda project: calls.append(("readiness",)) or readiness,
            "v63_source_pdf_integrity_audit": lambda project: calls.append(("source",)) or {"status": "NOT_TRACKED"},
            "v64_platform_upload_checklist": lambda project, readiness=None: calls.append(("checklist",)) or {"uploaded": False, "published": False},
            "v65_release_action_plan": lambda project, readiness=None, source_audit=None: calls.append(("plan",)) or {"task_count": 3},
            "v66_release_delivery_map": lambda project, readiness=None: calls.append(("map",)) or {"platform_count": 0},
        })
        report = self.ns["v67_run_publishing_workflow"](self.project)
        self.assertEqual(calls[0], ("listing", False))
        self.assertEqual(report["status"], "NEEDS_REVIEW")
        self.assertFalse(report["existing_listing_drafts_overwritten"])
        self.assertFalse(report["master_rebuilt"])
        self.assertFalse(report["uploaded"])
        self.assertFalse(report["published"])
        self.assertTrue((self.project / "REPORTS" / "PUBLISHING_RUN_SUMMARY.json").is_file())

    def test_menu_wiring_version_and_helper_uniqueness(self):
        self.assertIn('FACTORY_VERSION = "107.0"', self.source)
        self.assertIn('24. One-Click Publishing Run', self.source)
        self.assertIn('elif c=="24": v67_publishing_run_menu()', self.source)
        for name in NAMES:
            self.assertEqual(len([node for node in ast.walk(ast.parse(self.source))
                                  if isinstance(node, ast.FunctionDef) and node.name == name]), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
