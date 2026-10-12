"""Runtime tests for read-only production release preflight."""
import ast
import datetime as datetime_module
import hashlib
import pathlib
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
FACTORY_PATH = ROOT / "factory.py"


def load_preflight(namespace):
    source = FACTORY_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(FACTORY_PATH))
    matches = [
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "v20_release_preflight"
    ]
    if len(matches) != 1:
        raise AssertionError("v20_release_preflight must have exactly one definition")
    exec(compile(ast.Module(body=[matches[0]], type_ignores=[]), str(FACTORY_PATH), "exec"), namespace)
    return namespace["v20_release_preflight"]


class ReleasePreflightRuntimeTests(unittest.TestCase):
    def test_preflight_detects_missing_master_and_zero_byte_package_file_without_mutation(self):
        with tempfile.TemporaryDirectory() as temp:
            project = pathlib.Path(temp) / "SampleBook"
            package = project / "PLATFORMS" / "KDP"
            package.mkdir(parents=True)
            master = project / "MASTER.pdf"
            master.write_bytes(b"verified-master-placeholder")
            manifest = package / "PACKAGE_MANIFEST.json"
            manifest.write_text("{}", encoding="utf-8")
            artifact = package / "listing.txt"
            artifact.write_text("listing", encoding="utf-8")

            class FixedDateTime:
                @staticmethod
                def now():
                    return datetime_module.datetime(2026, 10, 12, 12, 0, 0)

            namespace = {
                "Path": pathlib.Path,
                "datetime": FixedDateTime,
                "FACTORY_VERSION": "30.0",
                "PLATFORM_DIRNAME": "PLATFORMS",
                "load_project_settings_safe": lambda path: {"title": "Sample Book"},
                "find_master_pdf": lambda path: master if master.is_file() else None,
                "file_hash": lambda path: hashlib.sha256(pathlib.Path(path).read_bytes()).hexdigest(),
                "load_platform_profiles": lambda: {
                    "KDP": {"enabled": True, "output_dir": "KDP"},
                    "Gumroad": {"enabled": False, "output_dir": "GUMROAD"},
                },
            }
            preflight = load_preflight(namespace)
            original_manifest = manifest.read_bytes()
            original_artifact = artifact.read_bytes()

            clean = preflight(project)
            self.assertTrue(clean["ready"])
            self.assertEqual(clean["master"]["sha256"], namespace["file_hash"](master))
            self.assertEqual(clean["platforms"]["KDP"]["status"], "PREFLIGHT_PASS")
            self.assertEqual(clean["platforms"].keys(), {"KDP"})
            self.assertEqual(manifest.read_bytes(), original_manifest)
            self.assertEqual(artifact.read_bytes(), original_artifact)

            empty_file = package / "empty.txt"
            empty_file.write_bytes(b"")
            blocked = preflight(project)
            self.assertFalse(blocked["ready"])
            self.assertTrue(any("ZERO_BYTE_FILE:PLATFORMS/KDP/empty.txt" in item["detail"].replace("\\\\", "/")
                                for item in blocked["blockers"]))

            master.unlink()
            missing_master = preflight(project)
            self.assertFalse(missing_master["ready"])
            self.assertEqual(missing_master["blockers"][0]["code"], "MASTER_MISSING")
            self.assertEqual(manifest.read_bytes(), original_manifest)
            self.assertEqual(artifact.read_bytes(), original_artifact)


if __name__ == "__main__":
    unittest.main()
