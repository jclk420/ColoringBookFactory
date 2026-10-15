"""Regression tests for the v59 read-only listing draft consistency audit."""
import ast
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FACTORY_PATH = ROOT / "factory.py"


def load_audit():
    source = FACTORY_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(FACTORY_PATH))
    nodes = [
        node for node in tree.body
        if isinstance(node, ast.FunctionDef)
        and node.name == "v59_listing_draft_consistency_audit"
    ]
    if len(nodes) != 1:
        raise AssertionError("Expected exactly one v59 audit function")

    def sanitized(name, limit):
        import re
        value = re.sub(r"[^A-Za-z0-9._-]+", "_", str(name or "file")).strip("._")
        return (value or "file")[:limit]

    namespace = {
        "Path": Path,
        "load_json": lambda path: json.loads(Path(path).read_text(encoding="utf-8")),
        "_platform_sanitized_filename": sanitized,
    }
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(FACTORY_PATH), "exec"), namespace)
    return namespace["v59_listing_draft_consistency_audit"]



def load_write_policy():
    source = FACTORY_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(FACTORY_PATH))
    nodes = [
        node for node in tree.body
        if isinstance(node, ast.FunctionDef)
        and node.name == "v60_listing_draft_write_policy"
    ]
    if len(nodes) != 1:
        raise AssertionError("Expected exactly one v60 listing write-policy function")
    namespace = {"Path": Path}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(FACTORY_PATH), "exec"), namespace)
    return namespace["v60_listing_draft_write_policy"]


def write_listing(root, platform="KDP", title="Test Book"):
    folder = root / platform
    folder.mkdir(parents=True, exist_ok=True)
    data = {
        "platform": platform,
        "title": title,
        "status": "REVIEW",
        "fields": {"book_title": title, "author": "J.A.C.", "description": "A horror coloring book.", "keywords": ["horror", "coloring"], "language": "English", "print_options": {"trim_size": "8.5 x 11 in"}},
        "quality_gate": {"status": "NEEDS_INPUT", "checks": [], "user_actions": []},
    }
    (folder / "LISTING.json").write_text(json.dumps(data), encoding="utf-8")
    (folder / "LISTING.txt").write_text(
        f"PLATFORM LISTING PACKAGE — {platform}\nProduct: {title}\n",
        encoding="utf-8",
    )
    return folder


class ListingDraftConsistencyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.audit = load_audit()
        self.write_policy = load_write_policy()

    def test_matching_json_and_text_pass_without_mutation(self):
        folder = write_listing(self.root)
        before_json = (folder / "LISTING.json").read_bytes()
        before_text = (folder / "LISTING.txt").read_bytes()

        report = self.audit(self.root, ["KDP"])

        self.assertEqual(report["status"], "PASS")
        self.assertEqual(report["error_count"], 0)
        self.assertTrue(report["read_only"])
        self.assertEqual((folder / "LISTING.json").read_bytes(), before_json)
        self.assertEqual((folder / "LISTING.txt").read_bytes(), before_text)

    def test_platform_and_title_mismatches_are_blocking(self):
        folder = write_listing(self.root, platform="KDP", title="JSON Title")
        text_path = folder / "LISTING.txt"
        text_path.write_text(
            "PLATFORM LISTING PACKAGE — Gumroad\nProduct: Different Title\n",
            encoding="utf-8",
        )

        report = self.audit(self.root, ["KDP"])
        codes = {item["code"] for item in report["findings"]}

        self.assertEqual(report["status"], "BLOCKED")
        self.assertIn("TEXT_TITLE_MISMATCH", codes)
        self.assertIn("TEXT_PLATFORM_MISMATCH", codes)

    def test_empty_required_field_is_flagged_for_review(self):
        folder = write_listing(self.root)
        data_path = folder / "LISTING.json"
        data = json.loads(data_path.read_text(encoding="utf-8"))
        data["fields"]["author"] = "   "
        data_path.write_text(json.dumps(data), encoding="utf-8")

        report = self.audit(self.root, ["KDP"])
        matches = [
            item for item in report["findings"]
            if item["code"] == "INCOMPLETE_FIELD" and "'author'" in item["message"]
        ]

        self.assertEqual(report["status"], "REVIEW")
        self.assertEqual(len(matches), 1)

    def test_missing_and_malformed_artifacts_are_reported_without_repair(self):
        folder = self.root / "Gumroad"
        folder.mkdir()
        bad_json = folder / "LISTING.json"
        bad_json.write_text("{broken", encoding="utf-8")
        before = bad_json.read_bytes()

        report = self.audit(self.root, ["Gumroad"])
        codes = {item["code"] for item in report["findings"]}

        self.assertEqual(report["status"], "BLOCKED")
        self.assertIn("UNREADABLE_JSON", codes)
        self.assertIn("MISSING_TEXT", codes)
        self.assertEqual(bad_json.read_bytes(), before)

    def test_existing_listing_pair_is_preserved_by_default(self):
        folder = write_listing(self.root)
        json_path = folder / "LISTING.json"
        text_path = folder / "LISTING.txt"
        before_json = json_path.read_bytes()
        before_text = text_path.read_bytes()

        policy = self.write_policy(json_path, text_path)

        self.assertFalse(policy["write"])
        self.assertEqual(policy["reason"], "preserve_existing")
        self.assertEqual(json_path.read_bytes(), before_json)
        self.assertEqual(text_path.read_bytes(), before_text)

    def test_partial_listing_pair_is_preserved_for_audit(self):
        folder = self.root / "KDP"
        folder.mkdir()
        json_path = folder / "LISTING.json"
        text_path = folder / "LISTING.txt"
        json_path.write_text("{malformed but user-owned}", encoding="utf-8")
        before_json = json_path.read_bytes()

        policy = self.write_policy(json_path, text_path)

        self.assertFalse(policy["write"])
        self.assertTrue(policy["existing_json"])
        self.assertFalse(policy["existing_text"])
        self.assertEqual(json_path.read_bytes(), before_json)
        self.assertFalse(text_path.exists())

    def test_explicit_overwrite_is_required_to_replace_existing_drafts(self):
        folder = write_listing(self.root)
        policy = self.write_policy(
            folder / "LISTING.json", folder / "LISTING.txt", overwrite_existing=True
        )

        self.assertTrue(policy["write"])
        self.assertEqual(policy["reason"], "explicit_overwrite")

    def test_new_listing_paths_can_be_created_without_overwrite(self):
        folder = self.root / "NewPlatform"
        policy = self.write_policy(
            folder / "LISTING.json", folder / "LISTING.txt"
        )

        self.assertTrue(policy["write"])
        self.assertEqual(policy["reason"], "new_drafts")


if __name__ == "__main__":
    unittest.main(verbosity=2)
