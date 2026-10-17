"""Platform preflight must respect split-mode per-part size limits."""
import ast
from datetime import datetime
from pathlib import Path
import tempfile
import unittest


FACTORY_PATH = Path(__file__).resolve().parents[1] / "factory.py"


def load_preflight(profile, pdf_info):
    source = FACTORY_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(FACTORY_PATH))
    matches = [
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "platform_preflight"
    ]
    if len(matches) != 1:
        raise AssertionError("platform_preflight must have exactly one definition")
    namespace = {
        "load_platform_profiles": lambda: {"Etsy": profile},
        "load_project_settings_safe": lambda _project: {},
        "inspect_pdf": lambda _pdf: dict(pdf_info),
        "platform_required_metadata": lambda _settings, _profile: [],
        "_platform_profile_warning_list": lambda _profile: [],
        "_kdp_profile_audit": lambda *_args: ([], []),
        "_platform_cover": lambda _project: None,
        "datetime": datetime,
        "FACTORY_VERSION": "test",
        "PLATFORM_ENGINE_VERSION": "test",
        "UNIVERSAL_PUBLISHING_VERSION": "test",
    }
    exec(compile(ast.Module(body=matches, type_ignores=[]), str(FACTORY_PATH), "exec"), namespace)
    return namespace["platform_preflight"]


class SplitModePreflightSizeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.project = Path(self.temp.name)
        self.pdf_info = {
            "exists": True,
            "error": None,
            "page_count": 30,
            "unique_sizes": ["8.5 x 11"],
            "sizes": [],
            "file_size_mb": 30.0,
        }
        self.rules = {
            "min_pages": 1,
            "max_pages": 10000,
            "require_title": False,
            "require_author": False,
            "require_cover": False,
            "require_landscape": False,
            "max_file_mb": 20,
            "expected_trim_from_project": False,
        }

    def test_etsy_split_mode_does_not_block_large_unsplit_master(self):
        profile = {
            "type": "digital",
            "rules": dict(self.rules),
            "variant": {"mode": "etsy_split"},
        }
        preflight = load_preflight(profile, self.pdf_info)
        report = preflight(self.project, "Etsy", self.project / "master.pdf", profile)
        self.assertNotEqual(report["status"], "BLOCKED")
        self.assertFalse(any("exceeds profile limit" in error for error in report["errors"]))

    def test_copy_mode_still_blocks_master_over_platform_file_limit(self):
        profile = {
            "type": "digital",
            "rules": dict(self.rules),
            "variant": {"mode": "copy"},
        }
        preflight = load_preflight(profile, self.pdf_info)
        report = preflight(self.project, "Digital PDF", self.project / "master.pdf", profile)
        self.assertEqual(report["status"], "BLOCKED")
        self.assertTrue(any("exceeds profile limit" in error for error in report["errors"]))


if __name__ == "__main__":
    unittest.main()
