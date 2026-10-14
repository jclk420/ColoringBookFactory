"""Runtime tests for the unified publishing release audit."""
import ast
import datetime
import pathlib
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
FACTORY_PATH = ROOT / "factory.py"


def load_audit(namespace):
    tree = ast.parse(FACTORY_PATH.read_text(encoding="utf-8"), filename=str(FACTORY_PATH))
    matches = [node for node in tree.body if isinstance(node, ast.FunctionDef)
               and node.name == "v56_publishing_release_audit"]
    if len(matches) != 1:
        raise AssertionError("v56_publishing_release_audit must have exactly one definition")
    exec(compile(ast.Module(body=[matches[0]], type_ignores=[]), str(FACTORY_PATH), "exec"), namespace)
    return namespace["v56_publishing_release_audit"]


class PublishingReleaseAuditTests(unittest.TestCase):
    def run_audit(self, preflight, package_report):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        project = pathlib.Path(temp.name) / "SampleBook"
        project.mkdir()
        (project / "REPORTS").mkdir()
        saved = {}
        namespace = {
            "Path": pathlib.Path,
            "datetime": datetime.datetime,
            "FACTORY_VERSION": "58.0",
            "v20_release_preflight": lambda path: preflight,
            "v23_package_manifest_verify": lambda path: package_report,
            "save_json": lambda path, data: saved.update({"path": pathlib.Path(path), "data": data}),
            "v12_active_project": lambda: None,
            "choose_project": lambda: None,
        }
        audit = load_audit(namespace)
        return audit(project), saved

    def test_clean_packages_are_ready_and_report_is_saved(self):
        result, saved = self.run_audit(
            {"ready": True, "blockers": []},
            {"overall_status": "READY", "platforms": {"KDP": {"errors": [], "warnings": []}}},
        )
        self.assertEqual(result["status"], "READY")
        self.assertTrue(result["ready_to_upload"])
        self.assertTrue(result["read_only"])
        self.assertEqual(saved["path"].name, "PUBLISHING_RELEASE_AUDIT.json")
        self.assertEqual(saved["data"]["status"], "READY")

    def test_package_error_blocks_upload_readiness(self):
        result, _ = self.run_audit(
            {"ready": True, "blockers": []},
            {"platforms": {"Gumroad": {"errors": ["SHA-256 mismatch: interior.pdf"], "warnings": []}}},
        )
        self.assertEqual(result["status"], "BLOCKED")
        self.assertFalse(result["ready_to_upload"])
        self.assertEqual(result["package_errors"][0]["platform"], "Gumroad")

    def test_package_warning_requires_review_but_does_not_claim_blocked(self):
        result, _ = self.run_audit(
            {"ready": True, "blockers": []},
            {"platforms": {"KDP": {"errors": [], "warnings": ["No recorded SHA-256 for: interior.pdf"]}}},
        )
        self.assertEqual(result["status"], "REVIEW")
        self.assertTrue(result["ready_to_upload"])
        self.assertEqual(len(result["package_warnings"]), 1)

    def test_preflight_blocker_prevents_ready_to_upload(self):
        result, _ = self.run_audit(
            {"ready": False, "blockers": [{"code": "MASTER_MISSING", "detail": "No MASTER PDF found"}]},
            {"platforms": {}},
        )
        self.assertEqual(result["status"], "BLOCKED")
        self.assertFalse(result["ready_to_upload"])
        self.assertEqual(result["blockers"][0]["code"], "MASTER_MISSING")


if __name__ == "__main__":
    unittest.main()
