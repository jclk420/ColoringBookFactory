"""Regression tests for the v93-v97 recovery and build-history center."""
import ast
import hashlib
import io
import json
import re
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import datetime
from pathlib import Path

FACTORY_PATH = Path(__file__).resolve().parents[1] / "factory.py"
NAMES = (
    "v83_backup_assembly_input",
    "v93_recovery_inventory",
    "v94_restore_assembly_input_backup",
    "v95_build_snapshot_integrity_audit",
    "v96_recovery_action_plan",
    "v97_run_recovery_center",
    "v97_recovery_center_menu",
)


def load_helpers():
    source = FACTORY_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(FACTORY_PATH))
    functions = {node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)}
    missing = [name for name in NAMES if name not in functions]
    if missing:
        raise AssertionError(f"Missing recovery helpers: {missing}")
    namespace = {"Path": Path, "json": json, "re": re, "datetime": datetime}
    module = ast.Module(body=[functions[name] for name in NAMES], type_ignores=[])
    exec(compile(module, str(FACTORY_PATH), "exec"), namespace)
    return namespace, source


class RecoveryCenterTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.project = self.root / "book"
        self.project.mkdir()
        self.ns, self.source = load_helpers()
        self.ns.update({
            "FACTORY_VERSION": "97.0",
            "IMAGE_EXTENSIONS": {".png", ".jpg", ".jpeg", ".webp"},
            "file_hash": lambda path: hashlib.sha256(Path(path).read_bytes()).hexdigest(),
        })

        def load_json(path):
            return json.loads(Path(path).read_text(encoding="utf-8"))

        def save_json(path, data):
            path = Path(path)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(data, indent=2), encoding="utf-8")

        self.ns.update({"load_json": load_json, "save_json": save_json})

    def create_backup(self, *, name="ASSEMBLY_INPUT_test", filename="old.png", data=b"old input"):
        folder = self.project / "_FACTORY_BACKUPS" / name
        folder.mkdir(parents=True)
        (folder / filename).write_bytes(data)
        (folder / "BACKUP_MANIFEST.json").write_text(json.dumps({
            "schema_version": 1, "verified": True,
            "files": [{"name": filename, "sha256": hashlib.sha256(data).hexdigest(), "size_bytes": len(data)}]
        }), encoding="utf-8")
        return folder

    def test_backup_function_writes_independent_verified_manifest(self):
        input_dir = self.project / "INPUT"
        input_dir.mkdir()
        (input_dir / "current.png").write_bytes(b"current")
        result = self.ns["v83_backup_assembly_input"](self.project, input_dir)
        self.assertEqual(result["status"], "BACKUP_VERIFIED")
        manifest_path = Path(result["backup_manifest"])
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        self.assertTrue(manifest["verified"])
        self.assertEqual(manifest["files"][0]["name"], "current.png")

    def test_recovery_inventory_verifies_backup_hashes(self):
        folder = self.create_backup()
        result = self.ns["v93_recovery_inventory"](self.project)
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["verified_backup_count"], 1)
        self.assertEqual(result["assembly_backups"][0]["status"], "VERIFIED")
        (folder / "old.png").write_bytes(b"tampered")
        result = self.ns["v93_recovery_inventory"](self.project)
        self.assertEqual(result["status"], "NEEDS_REVIEW")
        self.assertEqual(result["assembly_backups"][0]["status"], "BLOCKED")

    def test_restore_requires_confirmation_and_preserves_current_input(self):
        folder = self.create_backup(data=b"previous art")
        input_dir = self.project / "INPUT"
        input_dir.mkdir()
        current = input_dir / "current.png"
        current.write_bytes(b"current art")
        denied = self.ns["v94_restore_assembly_input_backup"](self.project, folder, confirm=False)
        self.assertEqual(denied["status"], "CONFIRMATION_REQUIRED")
        self.assertEqual(current.read_bytes(), b"current art")
        restored = self.ns["v94_restore_assembly_input_backup"](self.project, folder, confirm=True)
        self.assertEqual(restored["status"], "RESTORED")
        self.assertTrue(restored["restored"])
        self.assertFalse(current.exists())
        self.assertEqual((input_dir / "old.png").read_bytes(), b"previous art")
        self.assertEqual(restored["current_input_backup"]["status"], "BACKUP_VERIFIED")

    def test_restore_refuses_tampered_backup_without_changing_input(self):
        folder = self.create_backup()
        (folder / "old.png").write_bytes(b"tampered")
        input_dir = self.project / "INPUT"
        input_dir.mkdir()
        current = input_dir / "current.png"
        current.write_bytes(b"current")
        result = self.ns["v94_restore_assembly_input_backup"](self.project, folder, confirm=True)
        self.assertEqual(result["status"], "BLOCKED")
        self.assertEqual(current.read_bytes(), b"current")

    def test_build_snapshot_audit_checks_current_final_pdf_hash(self):
        final_dir = self.project / "FINAL"
        final_dir.mkdir()
        final_pdf = final_dir / "Book.pdf"
        final_pdf.write_bytes(b"final pdf")
        snapshot_dir = self.project / "BUILD_SNAPSHOTS"
        snapshot_dir.mkdir()
        snapshot = {"title": "Book", "timestamp": "2026-10-15T10:00:00",
                    "pages_built": 25, "final_pdf_sha256": hashlib.sha256(final_pdf.read_bytes()).hexdigest(),
                    "artwork": []}
        (snapshot_dir / "build_20261015-100000.json").write_text(json.dumps(snapshot), encoding="utf-8")
        result = self.ns["v95_build_snapshot_integrity_audit"](self.project)
        self.assertEqual(result["status"], "PASS")
        final_pdf.write_bytes(b"changed final")
        result = self.ns["v95_build_snapshot_integrity_audit"](self.project)
        self.assertEqual(result["status"], "NEEDS_REVIEW")
        self.assertTrue(any("differs from the latest build snapshot" in warning for warning in result["warnings"]))

    def test_recovery_plan_prioritizes_corrupt_backup(self):
        plan = self.ns["v96_recovery_action_plan"](self.project,
            {"assembly_backups": [{"status": "BLOCKED", "directory": "backup", "errors": ["Hash mismatch"]}]},
            {"status": "NEEDS_REVIEW", "warnings": ["Final PDF changed"]})
        self.assertGreaterEqual(plan["priority_counts"]["P0"], 1)
        self.assertGreaterEqual(plan["priority_counts"]["P1"], 1)
        self.assertEqual(plan["tasks"][0]["priority"], "P0")

    def test_recovery_center_chains_inventory_snapshot_audit_and_plan(self):
        calls = []
        self.ns.update({
            "v93_recovery_inventory": lambda project: calls.append("inventory") or {"status": "PASS", "verified_backup_count": 1, "build_snapshot_count": 2},
            "v95_build_snapshot_integrity_audit": lambda project: calls.append("build-audit") or {"status": "PASS"},
            "v96_recovery_action_plan": lambda *args: calls.append("plan") or {"task_count": 0},
        })
        result = self.ns["v97_run_recovery_center"](self.project)
        self.assertEqual(calls, ["inventory", "build-audit", "plan"])
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["verified_backup_count"], 1)
        self.assertFalse(result["restore_performed"])
        self.assertFalse(result["assembly_started"])

    def test_audit_menu_prints_result_instead_of_returning_silently(self):
        expected = {
            "status": "PASS", "project": str(self.project),
            "verified_backup_count": 2, "build_snapshot_count": 3,
            "build_snapshot_integrity": "PASS", "action_count": 0,
            "reports": {"action_plan": str(self.project / "REPORTS" / "RECOVERY_ACTION_PLAN.json")},
            "note": "Audit only.",
        }
        self.ns.update({
            "v12_active_project": lambda: self.project,
            "input": lambda prompt: "1",
            "v97_run_recovery_center": lambda project: expected,
        })
        output = io.StringIO()
        with redirect_stdout(output):
            result = self.ns["v97_recovery_center_menu"]()
        self.assertEqual(result, expected)
        printed = output.getvalue()
        self.assertIn("RECOVERY CENTER AUDIT", printed)
        self.assertIn("Overall status: PASS", printed)
        self.assertIn("Verified assembly backups: 2", printed)
        self.assertIn("Build snapshots found: 3", printed)
        self.assertIn("Recovery actions identified: 0", printed)
        self.assertIn("Recovery Action Plan report:", printed)

    def test_version_menu_and_build_backup_gate(self):
        self.assertIn('FACTORY_VERSION = "113.0"', self.source)
        self.assertIn('30. Recovery & Build History Center', self.source)
        self.assertIn('elif c=="30": v97_recovery_center_menu()', self.source)
        self.assertIn('assembly_gate = v76_assembly_readiness_gate(project)', self.source)
        self.assertIn('input_backup = v83_backup_assembly_input(project, input_dir)', self.source)
        tree = ast.parse(self.source)
        for name in NAMES:
            self.assertEqual(sum(1 for node in ast.walk(tree)
                                 if isinstance(node, ast.FunctionDef) and node.name == name), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
