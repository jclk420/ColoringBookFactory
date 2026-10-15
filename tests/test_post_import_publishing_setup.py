"""Runtime tests for v62 automatic post-import publishing preparation."""
import ast
import json
import tempfile
import unittest
from pathlib import Path

FACTORY_PATH = Path(__file__).resolve().parents[1] / "factory.py"


def load_helper():
    source = FACTORY_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(FACTORY_PATH))
    nodes = [node for node in tree.body
             if isinstance(node, ast.FunctionDef) and node.name == "v62_post_import_publishing_setup"]
    if len(nodes) != 1:
        raise AssertionError("Expected exactly one v62_post_import_publishing_setup definition")
    namespace = {"Path": Path}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(FACTORY_PATH), "exec"), namespace)
    return namespace["v62_post_import_publishing_setup"], namespace


class PostImportPublishingSetupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.project = Path(self.temp.name) / "book"
        self.project.mkdir()
        self.helper, self.ns = load_helper()
        self.calls = []
        self.saved = {}

        def listings(project, overwrite_existing=False):
            self.calls.append(("listings", Path(project), overwrite_existing))
            return {"status": "OK", "platforms": []}

        def readiness(project):
            self.calls.append(("readiness", Path(project)))
            return {"overall_status": "NEEDS_REVIEW"}

        def save_json(path, data):
            path = Path(path)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(data), encoding="utf-8")
            self.saved[str(path)] = data

        self.ns.update({
            "FACTORY_VERSION": "62.0",
            "MARKETING_DIR_NAME": "MARKETING",
            "v22_build_all_platform_listings": listings,
            "v61_upload_readiness_board": readiness,
            "save_json": save_json,
        })

    def test_runs_listing_generation_without_overwrite_and_readiness(self):
        result = self.helper(self.project, package_results=[{"status": "READY"}])
        self.assertEqual(self.calls[0], ("listings", self.project, False))
        self.assertEqual(self.calls[1], ("readiness", self.project))
        self.assertEqual(result["status"], "NEEDS_REVIEW")
        self.assertFalse(result["existing_listing_drafts_overwritten"])
        self.assertFalse(result["uploaded"])
        self.assertFalse(result["published"])
        self.assertTrue((self.project / "REPORTS" / "POST_IMPORT_PUBLISHING_PREP.json").is_file())

    def test_missing_project_is_blocked_without_running_builders(self):
        result = self.helper(self.project / "missing")
        self.assertEqual(result["status"], "BLOCKED")
        self.assertEqual(self.calls, [])

    def test_listing_builder_unexpected_return_is_reported_without_upload_claim(self):
        self.ns["v22_build_all_platform_listings"] = lambda *args, **kwargs: None
        result = self.helper(self.project)
        self.assertEqual(result["status"], "NEEDS_REVIEW")
        self.assertFalse(result["uploaded"])
        self.assertFalse(result["published"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
