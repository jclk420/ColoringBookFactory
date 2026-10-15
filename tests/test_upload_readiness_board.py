"""Runtime tests for the consolidated v61 platform upload readiness board."""
import ast
import datetime
import json
import tempfile
import unittest
from pathlib import Path

FACTORY_PATH = Path(__file__).resolve().parents[1] / "factory.py"


def load_board():
    source = FACTORY_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(FACTORY_PATH))
    nodes = [node for node in tree.body
             if isinstance(node, ast.FunctionDef) and node.name == "v61_upload_readiness_board"]
    if len(nodes) != 1:
        raise AssertionError("Expected exactly one v61_upload_readiness_board definition")
    namespace = {"Path": Path, "datetime": datetime.datetime, "json": json}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(FACTORY_PATH), "exec"), namespace)
    return namespace["v61_upload_readiness_board"], namespace


class UploadReadinessBoardTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.project = Path(self.temp.name) / "Sample Book"
        self.project.mkdir()
        self.board, self.namespace = load_board()
        self.saved = {}

        def save_json(path, data):
            path = Path(path)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(data, indent=2), encoding="utf-8")
            self.saved[str(path)] = data

        self.namespace.update({
            "FACTORY_VERSION": "61.0",
            "PLATFORM_DIRNAME": "PLATFORMS",
            "MARKETING_DIR_NAME": "MARKETING",
            "load_platform_profiles": lambda: {
                "KDP": {"enabled": True, "output_dir": "KDP"},
                "Gumroad": {"enabled": False, "output_dir": "GUMROAD"},
            },
            "v23_package_manifest_verify": lambda project: {
                "overall_status": "READY",
                "platforms": {"KDP": {"status": "READY", "errors": [], "warnings": []}},
            },
            "load_json": lambda path: json.loads(Path(path).read_text(encoding="utf-8")),
            "save_json": save_json,
            "_platform_sanitized_filename": lambda name, limit: name[:limit],
            "v12_active_project": lambda: self.project,
            "choose_project": lambda: self.project,
        })

    def write_listing_readiness(self, status="READY_FOR_REVIEW", errors=0):
        path = self.project / "MARKETING" / "LISTINGS" / "LISTING_READINESS.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({
            "platforms": [{"platform": "KDP", "status": status}],
            "draft_consistency_audit": {"error_count": errors, "warning_count": 0},
        }), encoding="utf-8")

    def test_clean_package_and_listing_are_ready_to_upload_not_published(self):
        self.write_listing_readiness()
        result = self.board(self.project)
        self.assertEqual(result["overall_status"], "READY_TO_UPLOAD")
        self.assertEqual(result["platforms"][0]["status"], "READY_TO_UPLOAD")
        self.assertFalse(result["uploaded"])
        self.assertFalse(result["published"])
        self.assertTrue(Path(self.project / "REPORTS" / "UPLOAD_READINESS.json").is_file())

    def test_missing_listing_draft_requires_review(self):
        result = self.board(self.project)
        self.assertEqual(result["overall_status"], "NEEDS_REVIEW")
        self.assertEqual(result["platforms"][0]["status"], "NEEDS_REVIEW")
        self.assertFalse(result["uploaded"])

    def test_package_blocker_cannot_be_marked_ready(self):
        self.write_listing_readiness()
        self.namespace["v23_package_manifest_verify"] = lambda project: {
            "overall_status": "BLOCKED",
            "platforms": {"KDP": {"status": "BLOCKED", "errors": ["SHA-256 mismatch: interior.pdf"], "warnings": []}},
        }
        result = self.board(self.project)
        self.assertEqual(result["overall_status"], "BLOCKED")
        self.assertIn("SHA-256 mismatch: interior.pdf", result["platforms"][0]["blockers"])

    def test_listing_consistency_errors_block_upload_readiness(self):
        self.write_listing_readiness(errors=1)
        result = self.board(self.project)
        self.assertEqual(result["overall_status"], "BLOCKED")
        self.assertTrue(any("consistency audit" in item for item in result["platforms"][0]["blockers"]))


if __name__ == "__main__":
    unittest.main(verbosity=2)
