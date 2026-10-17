"""Regression tests for exact, recursive package-manifest verification."""
import ast
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FACTORY_PATH = ROOT / "factory.py"


def load_verifier():
    tree = ast.parse(FACTORY_PATH.read_text(encoding="utf-8"), filename=str(FACTORY_PATH))
    matches = [node for node in tree.body if isinstance(node, ast.FunctionDef)
               and node.name == "v23_verify_package_root"]
    if len(matches) != 1:
        raise AssertionError("v23_verify_package_root must have exactly one definition")
    namespace = {
        "Path": Path,
        "load_json": lambda path: json.loads(Path(path).read_text(encoding="utf-8")),
        "file_hash": lambda path: hashlib.sha256(Path(path).read_bytes()).hexdigest(),
    }
    exec(compile(ast.Module(body=[matches[0]], type_ignores=[]), str(FACTORY_PATH), "exec"), namespace)
    return namespace["v23_verify_package_root"]


class PackageManifestExactnessTests(unittest.TestCase):
    def setUp(self):
        self.verify = load_verifier()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "KDP"
        self.root.mkdir()
        self.write_file("interior.pdf", b"interior PDF bytes")
        self.write_file("assets/cover.png", b"cover image bytes")
        self.write_manifest(["interior.pdf", "assets/cover.png"])

    def write_file(self, name, content):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        return path

    def write_manifest(self, names, hashes=None):
        if hashes is None:
            hashes = {name: hashlib.sha256((self.root / name).read_bytes()).hexdigest()
                      for name in names if (self.root / name).is_file()}
        (self.root / "PACKAGE_MANIFEST.json").write_text(json.dumps({
            "schema_version": 1, "files": names, "file_hashes": hashes
        }), encoding="utf-8")

    def test_exact_recursive_manifest_is_ready(self):
        result = self.verify(self.root)
        self.assertEqual(result["status"], "READY", result)
        self.assertEqual(result["checked_files"], 2)
        self.assertEqual(result["actual_files"], ["assets/cover.png", "interior.pdf"])

    def test_unlisted_nested_file_blocks_readiness(self):
        self.write_file("assets/preview.png", b"untracked")
        result = self.verify(self.root)
        self.assertEqual(result["status"], "BLOCKED")
        self.assertIn("assets/preview.png", result["unexpected_files"])
        self.assertTrue(any("Unexpected files not listed" in item for item in result["errors"]))

    def test_changed_nested_file_fails_hash_verification(self):
        self.write_file("assets/cover.png", b"changed cover")
        result = self.verify(self.root)
        self.assertEqual(result["status"], "BLOCKED")
        self.assertTrue(any("SHA-256 mismatch: assets/cover.png" in item for item in result["errors"]))

    def test_duplicate_and_path_traversal_entries_are_blocked(self):
        self.write_manifest(["interior.pdf", "interior.pdf", "../outside.txt"])
        result = self.verify(self.root)
        self.assertEqual(result["status"], "BLOCKED")
        self.assertTrue(any("Duplicate manifest path" in item for item in result["errors"]))
        self.assertTrue(any("Unsafe manifest path" in item for item in result["errors"]))

    def test_missing_hash_is_review_and_not_ready(self):
        self.write_manifest(["interior.pdf", "assets/cover.png"], hashes={})
        result = self.verify(self.root)
        self.assertEqual(result["status"], "REVIEW")
        self.assertEqual(len(result["warnings"]), 2)

    def test_symlink_inside_package_blocks_readiness(self):
        outside = Path(self.temp.name) / "outside.txt"
        outside.write_text("outside", encoding="utf-8")
        link = self.root / "assets" / "outside-link.txt"
        try:
            link.symlink_to(outside)
        except (OSError, NotImplementedError) as error:
            self.skipTest(f"symlinks unavailable: {error}")
        result = self.verify(self.root)
        self.assertEqual(result["status"], "BLOCKED")
        self.assertIn("assets/outside-link.txt", result["symlink_paths"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
