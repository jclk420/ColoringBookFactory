"""Runtime tests for immutable build snapshot creation."""
import ast
import datetime as datetime_module
import json
import os
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FACTORY_PATH = ROOT / "factory.py"


def load_snapshot_helpers():
    source = FACTORY_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(FACTORY_PATH))
    wanted = {"save_json_no_clobber", "create_build_snapshot"}
    nodes = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in wanted]
    if {node.name for node in nodes} != wanted:
        raise AssertionError("Expected snapshot writer helpers exactly once")

    class FixedDateTime:
        @staticmethod
        def now():
            return datetime_module.datetime(2026, 10, 13, 12, 0, 0)

    namespace = {
        "Path": Path, "json": json, "os": os, "datetime": FixedDateTime,
        "FACTORY_VERSION": "58.0",
        "artwork_identity_id": lambda image: "ART-TEST",
        "artifact_sha256": lambda path: "a" * 64,
    }
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(FACTORY_PATH), "exec"), namespace)
    return namespace


class BuildSnapshotSafetyTests(unittest.TestCase):
    def test_same_second_snapshots_never_overwrite_existing_audit_records(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            project = root / "Book"
            snapshots = project / "BUILD_SNAPSHOTS"
            snapshots.mkdir(parents=True)
            original = snapshots / "build_20261013-120000.json"
            original.write_text('{"preserve": true}', encoding="utf-8")
            final_pdf = project / "Book.pdf"
            final_pdf.write_bytes(b"pdf")
            image = type("ImageFixture", (), {"name": "art.png"})()
            helpers = load_snapshot_helpers()
            build = helpers["create_build_snapshot"]
            first = build(project, {"title": "Book"}, {"pages": []}, [image], [object()], final_pdf)
            second = build(project, {"title": "Book"}, {"pages": []}, [image], [object()], final_pdf)
            self.assertEqual(original.read_text(encoding="utf-8"), '{"preserve": true}')
            self.assertEqual(first.name, "build_20261013-120000_02.json")
            self.assertEqual(second.name, "build_20261013-120000_03.json")
            self.assertNotEqual(first, second)
            self.assertEqual(json.loads(first.read_text(encoding="utf-8"))["title"], "Book")
            self.assertEqual(json.loads(second.read_text(encoding="utf-8"))["title"], "Book")

    def test_snapshot_creation_can_be_disabled_without_writes(self):
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp) / "Book"
            helpers = load_snapshot_helpers()
            result = helpers["create_build_snapshot"](project, {"build_snapshots_enabled": False}, {}, [], [], project / "missing.pdf")
            self.assertIsNone(result)
            self.assertFalse(project.exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
