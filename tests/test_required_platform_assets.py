"""Required platform deliverables must fail closed when missing."""
import ast
import hashlib
import json
import re
from pathlib import Path
import unittest


FACTORY_PATH = Path(__file__).resolve().parents[1] / "factory.py"


class _ImageProbe:
    """Small dependency-free image decoder stand-in for AST-isolated tests."""
    def __init__(self, path):
        self.path = Path(path)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False

    def verify(self):
        data = self.path.read_bytes()
        if data.startswith(b"\\x89PNG\\r\\n\\x1a\\n"):
            if b"IEND\\xaeB\\x60\\x82" not in data:
                raise ValueError("truncated or corrupt PNG payload")
        elif data.startswith(b"\\xff\\xd8\\xff"):
            if not data.endswith(b"\\xff\\xd9"):
                raise ValueError("truncated JPEG payload")
        elif data.startswith(b"RIFF") and data[8:12] == b"WEBP":
            if len(data) < 16:
                raise ValueError("truncated WebP payload")
        else:
            raise ValueError("unsupported or malformed image payload")


class _ImageModule:
    @staticmethod
    def open(path):
        return _ImageProbe(path)


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
        "json": json,
        "re": re,
        "inspect_pdf": lambda path: {"error": None},
        "file_hash": lambda path: hashlib.sha256(Path(path).read_bytes()).hexdigest(),
        "Image": _ImageModule,
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

    def test_corrupt_unrequired_image_still_blocks_package(self):
        profile = {"files": ["interior_pdf"], "variant": {"mode": "copy"}}
        extra_image = self.root / "bonus.png"
        extra_image.write_bytes(b"not actually a PNG")
        errors, _ = self.validate(
            self.root, self.master, profile, [self.interior, extra_image]
        )
        self.assertTrue(any("Generated image is invalid" in item for item in errors))

    def test_image_with_valid_signature_but_corrupt_payload_blocks_package(self):
        profile = {"files": ["interior_pdf"], "variant": {"mode": "copy"}}
        extra_image = self.root / "bonus.png"
        extra_image.write_bytes(b"\\x89PNG\\r\\n\\x1a\\n" + b"valid header, corrupt payload")
        errors, _ = self.validate(
            self.root, self.master, profile, [self.interior, extra_image]
        )
        self.assertTrue(any("Generated image failed full image verification" in item for item in errors))

    def test_metadata_json_must_match_current_master_fingerprint(self):
        profile = {"files": ["interior_pdf", "metadata"], "variant": {"mode": "copy"}}
        master_hash = hashlib.sha256(self.master.read_bytes()).hexdigest()
        metadata = self.root / "METADATA.json"
        metadata.write_text(json.dumps({
            "title": "Book", "platform": "Digital PDF",
            "source_master_sha256": master_hash,
        }), encoding="utf-8")
        errors, _ = self.validate(
            self.root, self.master, profile, [self.interior, metadata]
        )
        self.assertFalse(any("Metadata source MASTER SHA-256" in item for item in errors))

        metadata.write_text(json.dumps({
            "title": "Book", "platform": "Digital PDF",
            "source_master_sha256": "0" * 64,
        }), encoding="utf-8")
        errors, _ = self.validate(
            self.root, self.master, profile, [self.interior, metadata]
        )
        self.assertTrue(any("Metadata source MASTER SHA-256 is stale" in item for item in errors))

    def test_malformed_metadata_json_blocks_package(self):
        profile = {"files": ["interior_pdf", "metadata"], "variant": {"mode": "copy"}}
        metadata = self.root / "METADATA.json"
        metadata.write_text("{not valid json", encoding="utf-8")
        errors, _ = self.validate(
            self.root, self.master, profile, [self.interior, metadata]
        )
        self.assertTrue(any("Required metadata JSON is invalid" in item for item in errors))

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
