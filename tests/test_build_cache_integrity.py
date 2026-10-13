"""Runtime tests for cache completeness and package checksum verification."""
import ast
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FACTORY_PATH = ROOT / "factory.py"


def load_cache_helpers():
    source = FACTORY_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(FACTORY_PATH))
    wanted = {"package_checksums_valid", "cached_build_is_complete"}
    nodes = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in wanted]
    if {node.name for node in nodes} != wanted:
        raise AssertionError("Expected cache integrity helpers exactly once")

    def file_hash(path):
        digest = hashlib.sha256()
        with open(path, "rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    namespace = {"Path": Path, "json": json, "file_hash": file_hash,
                 "load_json": lambda path: json.loads(Path(path).read_text(encoding="utf-8"))}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(FACTORY_PATH), "exec"), namespace)
    return namespace


class BuildCacheIntegrityTests(unittest.TestCase):
    def make_fixture(self, root):
        project = root / "Book"
        package = project / "KDP_PACKAGE"
        package.mkdir(parents=True)
        (project / "FINAL").mkdir()
        (project / "REPORTS").mkdir()
        final_pdf = project / "FINAL" / "Book.pdf"
        final_pdf.write_bytes(b"interior pdf bytes")
        report = project / "REPORTS" / "final_report.txt"
        report.write_text("STATUS: BUILD SUCCESSFUL\n", encoding="utf-8")
        (package / "Interior.pdf").write_bytes(final_pdf.read_bytes())
        (package / "BUILD_REPORT.txt").write_text(report.read_text(encoding="utf-8"), encoding="utf-8")
        (package / "KDP_CHECKLIST.txt").write_text("checklist", encoding="utf-8")
        (package / "PRODUCTION_READINESS.txt").write_text("readiness", encoding="utf-8")
        (package / "kdp_manifest.json").write_text(json.dumps({"interior_pdf": "Interior.pdf", "cover_pdf": None}), encoding="utf-8")
        settings = {"kdp_generate_cover": False, "metadata_export_enabled": False,
                    "production_manifest_enabled": False, "checksum_artifacts": False,
                    "build_snapshots_enabled": False}
        return project, package, final_pdf, report, settings

    def test_cache_accepts_complete_matching_core_artifacts(self):
        with tempfile.TemporaryDirectory() as temp:
            project, _package, final_pdf, report, settings = self.make_fixture(Path(temp))
            helpers = load_cache_helpers()
            self.assertTrue(helpers["cached_build_is_complete"](project, settings, final_pdf, report))

    def test_cache_rejects_missing_readiness_and_mismatched_interior(self):
        with tempfile.TemporaryDirectory() as temp:
            project, package, final_pdf, report, settings = self.make_fixture(Path(temp))
            helpers = load_cache_helpers()
            (package / "Interior.pdf").write_bytes(b"tampered")
            self.assertFalse(helpers["cached_build_is_complete"](project, settings, final_pdf, report))
            (package / "Interior.pdf").write_bytes(final_pdf.read_bytes())
            (package / "PRODUCTION_READINESS.txt").unlink()
            self.assertFalse(helpers["cached_build_is_complete"](project, settings, final_pdf, report))

    def test_checksum_manifest_detects_tampering_and_missing_files(self):
        with tempfile.TemporaryDirectory() as temp:
            package = Path(temp)
            artifact = package / "artifact.txt"
            artifact.write_text("original", encoding="utf-8")
            digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
            sums = package / "SHA256SUMS.txt"
            sums.write_text(f"{digest}  artifact.txt\n", encoding="utf-8")
            helpers = load_cache_helpers()
            self.assertTrue(helpers["package_checksums_valid"](package))
            artifact.write_text("tampered", encoding="utf-8")
            self.assertFalse(helpers["package_checksums_valid"](package))
            artifact.write_text("original", encoding="utf-8")
            (package / "unexpected.txt").write_text("extra", encoding="utf-8")
            self.assertFalse(helpers["package_checksums_valid"](package))

    def test_cache_rejects_unsafe_manifest_names(self):
        with tempfile.TemporaryDirectory() as temp:
            project, package, final_pdf, report, settings = self.make_fixture(Path(temp))
            (package / "kdp_manifest.json").write_text(json.dumps({"interior_pdf": "../outside.pdf", "cover_pdf": None}), encoding="utf-8")
            helpers = load_cache_helpers()
            self.assertFalse(helpers["cached_build_is_complete"](project, settings, final_pdf, report))


if __name__ == "__main__":
    unittest.main(verbosity=2)
