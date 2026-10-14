"""Runtime tests for platform readiness, freshness checks, and manual upload checklist."""
import ast
import datetime
import json
import pathlib
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
FACTORY_PATH = ROOT / "factory.py"


def load_function(namespace):
    tree = ast.parse(FACTORY_PATH.read_text(encoding="utf-8"), filename=str(FACTORY_PATH))
    matches = [node for node in tree.body if isinstance(node, ast.FunctionDef)
               and node.name == "v57_publishing_readiness_bundle"]
    if len(matches) != 1:
        raise AssertionError("v57_publishing_readiness_bundle must have exactly one definition")
    exec(compile(ast.Module(body=[matches[0]], type_ignores=[]), str(FACTORY_PATH), "exec"), namespace)
    return namespace["v57_publishing_readiness_bundle"]


class PublishingReadinessTests(unittest.TestCase):
    def run_check(self, master_hash="abc123", recorded_hash="abc123", settings=None, enabled=True):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        project = pathlib.Path(temp.name) / "SampleBook"
        root = project / "PLATFORMS" / "KDP"
        root.mkdir(parents=True)
        (project / "MASTER").mkdir()
        master = project / "MASTER" / "Sample_MASTER.pdf"
        master.write_bytes(b"test pdf placeholder")
        (project / "REPORTS").mkdir()
        manifest = {"master_sha256": recorded_hash, "files": ["interior.pdf"], "file_hashes": {"interior.pdf": "xyz"}}
        (root / "PACKAGE_MANIFEST.json").write_text(json.dumps(manifest), encoding="utf-8")
        (root / "interior.pdf").write_bytes(b"package pdf")
        saved = {}
        profile = {"enabled": enabled, "output_dir": "KDP", "rules": {"min_pages": 24, "max_pages": 828,
                   "max_files": 2, "max_file_mb": 650, "require_title": True}}
        package = {"platforms": {"KDP": {"errors": [], "warnings": []}}}
        namespace = {
            "Path": pathlib.Path, "datetime": datetime.datetime, "FACTORY_VERSION": "58.0",
            "PLATFORM_DIRNAME": "PLATFORMS",
            "v12_active_project": lambda: None, "choose_project": lambda: None,
            "load_project_settings_safe": lambda p: settings or {"title": "Sample Book", "description": "Good description", "keywords": ["horror"], "categories": ["crafts"]},
            "find_master_pdf": lambda p: master, "file_hash": lambda p: master_hash,
            "v20_release_preflight": lambda p: {"ready": True, "blockers": []},
            "v23_package_manifest_verify": lambda p: package,
            "load_platform_profiles": lambda: {"KDP": profile},
            "platform_required_metadata": lambda data, prof: [] if data.get("title") else ["Required metadata missing: title."],
            "load_json": lambda p: json.loads(pathlib.Path(p).read_text(encoding="utf-8")),
            "pdf_page_count": lambda p: 30,
            "save_json": lambda p, data: saved.update({"path": pathlib.Path(p), "data": data}),
            "print": lambda *args, **kwargs: None,
        }
        function = load_function(namespace)
        return function(project), saved

    def test_matching_master_fingerprint_passes_platform_freshness(self):
        result, saved = self.run_check()
        self.assertEqual(result["status"], "READY")
        self.assertEqual(result["platforms"]["KDP"]["status"], "READY")
        self.assertTrue(result["read_only"])
        self.assertEqual(saved["path"].name, "PUBLISHING_READINESS_CHECKLIST.json")
        self.assertTrue(saved["data"]["checklist"][-1]["required"])

    def test_stale_package_master_hash_blocks_readiness(self):
        result, _ = self.run_check(recorded_hash="older-hash")
        self.assertEqual(result["status"], "BLOCKED")
        self.assertTrue(any("STALE_PACKAGE" in row["detail"] for row in result["blockers"]))

    def test_missing_source_fingerprint_requires_review(self):
        result, _ = self.run_check(recorded_hash=None)
        self.assertEqual(result["status"], "REVIEW")
        self.assertTrue(any("freshness cannot be confirmed" in row["detail"] for row in result["warnings"]))

    def test_missing_listing_description_is_flagged(self):
        result, _ = self.run_check(settings={"title": "Sample Book"})
        self.assertEqual(result["status"], "REVIEW")
        self.assertTrue(any("description is empty" in row["detail"] for row in result["warnings"]))

    def test_no_enabled_platforms_blocks_readiness(self):
        result, _ = self.run_check(enabled=False)
        self.assertEqual(result["status"], "BLOCKED")
        self.assertFalse(result["ready_to_upload"])


if __name__ == "__main__":
    unittest.main()
