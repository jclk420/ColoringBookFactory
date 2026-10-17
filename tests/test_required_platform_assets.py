"""Required platform deliverables must fail closed when missing."""
import ast
import hashlib
from pathlib import Path
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
    module = ast.Module(body=matches, type_ignores=[])
    exec(compile(module, str(FACTORY_PATH), "exec"), namespace)
    return namespace["validate_generated_package"]


class RequiredPlatformAssetTests(unittest.TestCase):
    def setUp(self):
        self.validate = load_validator()
        self.temp = __import__("tempfile").TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.master = self.root / "Book_MASTER.pdf"
        self.master.write_bytes(b"same master content")
        self.interior = self.root / "Book_DIGITAL.pdf"
        self.interior.write_bytes(self.master.read_bytes())
        self.profile = {
            "files": ["interior_pdf", "cover_pdf"],
            "variant": {"mode": "copy"},
        }

    def test_missing_required_cover_pdf_is_blocking_error(self):
        errors, warnings = self.validate(
            self.root, self.master, self.profile, [self.interior]
        )
        self.assertTrue(any("Required platform cover PDF is missing" in item for item in errors))
        self.assertFalse(any("cover PDF" in item for item in warnings))

    def test_cover_image_does_not_satisfy_cover_pdf_requirement(self):
        cover_image = self.root / "Book_COVER.png"
        cover_image.write_bytes(b"not a PDF")
        errors, _ = self.validate(
            self.root, self.master, self.profile, [self.interior, cover_image]
        )
        self.assertTrue(any("Required platform cover PDF is missing" in item for item in errors))

    def test_real_cover_pdf_satisfies_required_cover_asset(self):
        cover_pdf = self.root / "Book_COVER.pdf"
        cover_pdf.write_bytes(b"cover pdf")
        errors, _ = self.validate(
            self.root, self.master, self.profile, [self.interior, cover_pdf]
        )
        self.assertFalse(any("Required platform cover PDF is missing" in item for item in errors))
        self.assertFalse(any("Variant integrity mismatch" in item for item in errors))

    def test_cover_pdf_alone_does_not_satisfy_required_interior_pdf(self):
        cover_pdf = self.root / "Book_COVER.pdf"
        cover_pdf.write_bytes(b"cover pdf")
        errors, _ = self.validate(
            self.root, self.master, self.profile, [cover_pdf]
        )
        self.assertTrue(any("Required interior PDF was not generated" in item for item in errors))

    def test_empty_required_preview_sheet_blocks_package(self):
        profile = {"files": ["interior_pdf", "preview_sheet"], "variant": {"mode": "copy"}}
        preview = self.root / "PREVIEW_SHEET.png"
        preview.write_bytes(b"")
        errors, _ = self.validate(
            self.root, self.master, profile, [self.interior, preview]
        )
        self.assertTrue(any("Required artifact is empty: PREVIEW_SHEET.png" in item for item in errors))

    def test_nonempty_but_invalid_preview_sheet_blocks_package(self):
        profile = {"files": ["interior_pdf", "preview_sheet"], "variant": {"mode": "copy"}}
        preview = self.root / "PREVIEW_SHEET.png"
        preview.write_bytes(b"not actually a PNG")
        errors, _ = self.validate(
            self.root, self.master, profile, [self.interior, preview]
        )
        self.assertTrue(any("Required preview sheet is not a valid PNG image" in item for item in errors))

    def test_empty_required_metadata_blocks_package(self):
        profile = {"files": ["interior_pdf", "metadata"], "variant": {"mode": "copy"}}
        metadata = self.root / "METADATA.json"
        metadata.write_bytes(b"")
        errors, _ = self.validate(
            self.root, self.master, profile, [self.interior, metadata]
        )
        self.assertTrue(any("Required artifact is empty: METADATA.json" in item for item in errors))

    def test_generator_enforces_package_validation_before_manifest(self):
        tree = ast.parse(FACTORY_PATH.read_text(encoding="utf-8"), filename=str(FACTORY_PATH))
        generator = next(
            node for node in tree.body
            if isinstance(node, ast.FunctionDef) and node.name == "generate_platform_package_v112"
        )
        calls = [
            (node.lineno, node.func.id)
            for node in ast.walk(generator)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        ]
        validation_lines = [line for line, name in calls if name == "validate_generated_package"]
        manifest_lines = [
            node.lineno for node in ast.walk(generator)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "save_json"
            and any(
                isinstance(arg, ast.Name) and arg.id == "manifest_path"
                for arg in node.args
            )
        ]
        self.assertTrue(validation_lines, "generator must invoke the package validator")
        self.assertTrue(manifest_lines, "generator must write the package manifest")
        self.assertLess(
            min(validation_lines), min(manifest_lines),
            "package validation must run before manifest creation/publishing",
        )


if __name__ == "__main__":
    unittest.main()
