"""Profile-required deliverables must be present before a platform package is published."""
import ast
import hashlib
from pathlib import Path
import tempfile
import unittest


FACTORY_PATH = Path(__file__).resolve().parents[1] / "factory.py"


def load_validator():
    tree = ast.parse(FACTORY_PATH.read_text(encoding="utf-8"), filename=str(FACTORY_PATH))
    matches = [
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "validate_generated_package"
    ]
    if len(matches) != 1:
        raise AssertionError("validate_generated_package must have exactly one definition")
    namespace = {
        "Path": Path,
        "inspect_pdf": lambda path: {"error": None},
        "file_hash": lambda path: hashlib.sha256(Path(path).read_bytes()).hexdigest(),
    }
    exec(compile(ast.Module(body=matches, type_ignores=[]), str(FACTORY_PATH), "exec"), namespace)
    return namespace["validate_generated_package"]


class RequiredProfileDeliverableTests(unittest.TestCase):
    def setUp(self):
        self.validate = load_validator()
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.master = self.root / "MASTER.pdf"
        self.master.write_bytes(b"same interior")
        self.interior = self.root / "Book_DIGITAL.pdf"
        self.interior.write_bytes(self.master.read_bytes())
        self.profile = {"files": ["digital_pdf", "cover_preview", "checklist"], "variant": {"mode": "copy"}}

    def test_missing_cover_preview_is_blocking(self):
        checklist = self.root / "PLATFORM_UPLOAD_CHECKLIST.txt"
        checklist.write_text("checklist", encoding="utf-8")
        errors, _ = self.validate(self.root, self.master, self.profile, [self.interior, checklist])
        self.assertTrue(any("Required cover preview image is missing" in error for error in errors))

    def test_missing_checklist_is_blocking(self):
        cover = self.root / "cover.png"
        cover.write_bytes(b"\\x89PNG\\r\\n\\x1a\\n\\x00\\x00\\x00\\x0dIHDR")
        errors, _ = self.validate(self.root, self.master, self.profile, [self.interior, cover])
        self.assertTrue(any("Required platform upload checklist is missing" in error for error in errors))

    def test_valid_cover_preview_and_checklist_satisfy_profile(self):
        cover = self.root / "cover.png"
        cover.write_bytes(b"image placeholder")
        checklist = self.root / "PLATFORM_UPLOAD_CHECKLIST.txt"
        checklist.write_text("checklist", encoding="utf-8")
        errors, _ = self.validate(
            self.root, self.master, self.profile, [self.interior, cover, checklist]
        )
        self.assertFalse(any("Required cover preview image is missing" in error for error in errors))
        self.assertFalse(any("Required platform upload checklist is missing" in error for error in errors))

    def test_corrupt_cover_preview_is_blocking(self):
        cover = self.root / "cover.png"
        cover.write_bytes(b"not really a PNG image")
        checklist = self.root / "PLATFORM_UPLOAD_CHECKLIST.txt"
        checklist.write_text("checklist", encoding="utf-8")
        errors, _ = self.validate(self.root, self.master, self.profile, [self.interior, cover, checklist])
        self.assertTrue(any("Required cover preview image is invalid" in error for error in errors))

    def test_generator_writes_checklist_before_package_validation(self):
        tree = ast.parse(FACTORY_PATH.read_text(encoding="utf-8"), filename=str(FACTORY_PATH))
        generator = next(
            node for node in tree.body
            if isinstance(node, ast.FunctionDef) and node.name == "generate_platform_package_v112"
        )
        checklist_lines = [
            node.lineno for node in ast.walk(generator)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "write_text"
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "checklist_path"
        ]
        validation_lines = [
            node.lineno for node in ast.walk(generator)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "validate_generated_package"
        ]
        self.assertTrue(checklist_lines, "generator must create the promised checklist")
        self.assertTrue(validation_lines, "generator must call the package validator")
        self.assertLess(min(checklist_lines), min(validation_lines))


if __name__ == "__main__":
    unittest.main()
