"""Filesystem tests for transactional publishing and rollback."""
import ast
from pathlib import Path
import shutil
import tempfile
import unittest


FACTORY_PATH = Path(__file__).resolve().parents[1] / "factory.py"


def load_publish_helper():
    source = FACTORY_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(FACTORY_PATH))
    matches = [
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "_publish_staged_package"
    ]
    if len(matches) != 1:
        raise AssertionError("_publish_staged_package must have exactly one definition")
    namespace = {"Path": Path, "shutil": shutil}
    exec(compile(ast.Module(body=matches, type_ignores=[]), str(FACTORY_PATH), "exec"), namespace)
    return namespace["_publish_staged_package"]


class TransactionalPlatformPublishTests(unittest.TestCase):
    def setUp(self):
        self.publish = load_publish_helper()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.root = self.base / "KDP"
        self.staging = self.base / ".KDP.staging"

    def test_failed_post_publish_validation_restores_previous_package(self):
        self.root.mkdir()
        (self.root / "old.txt").write_text("known-good", encoding="utf-8")
        self.staging.mkdir()
        (self.staging / "new.txt").write_text("candidate", encoding="utf-8")

        def reject(_root):
            return ["simulated final validation failure"], []

        with self.assertRaisesRegex(RuntimeError, "simulated final validation failure"):
            self.publish(self.staging, self.root, reject)

        self.assertEqual((self.root / "old.txt").read_text(encoding="utf-8"), "known-good")
        self.assertFalse((self.root / "new.txt").exists())
        self.assertFalse(self.staging.exists())
        self.assertFalse((self.base / "KDP.previous").exists())

    def test_successful_publish_replaces_previous_package(self):
        self.root.mkdir()
        (self.root / "old.txt").write_text("old", encoding="utf-8")
        self.staging.mkdir()
        (self.staging / "new.txt").write_text("new", encoding="utf-8")

        warnings = self.publish(self.staging, self.root, lambda _root: ([], ["review it"]))

        self.assertEqual((self.root / "new.txt").read_text(encoding="utf-8"), "new")
        self.assertFalse((self.root / "old.txt").exists())
        self.assertFalse((self.base / "KDP.previous").exists())
        self.assertEqual(warnings, ["review it"])

    def test_failed_first_publish_leaves_no_partial_package(self):
        self.staging.mkdir()
        (self.staging / "new.txt").write_text("candidate", encoding="utf-8")

        with self.assertRaisesRegex(RuntimeError, "simulated failure"):
            self.publish(
                self.staging, self.root,
                lambda _root: (["simulated failure"], []),
            )

        self.assertFalse(self.root.exists())
        self.assertFalse(self.staging.exists())

    def test_generator_verifies_staged_manifest_before_publish(self):
        source = FACTORY_PATH.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(FACTORY_PATH))
        generator = next(
            node for node in tree.body
            if isinstance(node, ast.FunctionDef)
            and node.name == "generate_platform_package_v112"
        )
        body = ast.get_source_segment(source, generator)
        self.assertIsNotNone(body)
        self.assertIn("staged_verification = v23_verify_package_root(staging)", body)
        self.assertIn("if staged_verification.get(\"errors\")", body)
        self.assertLess(
            body.index("staged_verification = v23_verify_package_root(staging)"),
            body.index("_publish_staged_package(staging, root, validator)"),
            "manifest and inventory verification must pass before publication",
        )


if __name__ == "__main__":
    unittest.main()
