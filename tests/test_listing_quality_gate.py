"""Regression tests for the v29 platform listing quality gate."""
import ast
import datetime as datetime_module
import json
import pathlib
import re
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
FACTORY_PATH = ROOT / "factory.py"


def load_gate():
    source = FACTORY_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(FACTORY_PATH))
    matches = [
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "v29_listing_quality_gate"
    ]
    if len(matches) != 1:
        raise AssertionError("v29_listing_quality_gate must have exactly one definition")
    module = ast.Module(body=[matches[0]], type_ignores=[])
    namespace = {}
    exec(compile(module, str(FACTORY_PATH), "exec"), namespace)
    return namespace["v29_listing_quality_gate"]


class ListingQualityGateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.gate = staticmethod(load_gate())

    def test_complete_gumroad_listing_is_ready_for_review(self):
        fields = {
            "name": "Nightmare Cryptids",
            "description": "A horror coloring adventure.",
            "tags": ["horror", "coloring"],
            "author": "J.A.C.",
            "license_terms": "Personal use only.",
            "price": 7.99,
        }
        result = self.gate(
            "Gumroad", fields, master_exists=True, cover_exists=True, profile_enabled=True
        )
        self.assertEqual(result["status"], "READY_FOR_REVIEW")
        self.assertEqual(result["score_percent"], 100)
        self.assertEqual(result["missing_required"], [])
        self.assertEqual(result["user_actions"], [])
        self.assertFalse(result["published"])

    def test_gumroad_and_payhip_listing_builders_supply_author_to_quality_gate(self):
        source = FACTORY_PATH.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(FACTORY_PATH))
        matches = [node for node in tree.body
                   if isinstance(node, ast.FunctionDef) and node.name == "v22_build_platform_listing"]
        self.assertEqual(len(matches), 1)
        node = matches[0]
        branches = {}
        for child in ast.walk(node):
            if isinstance(child, ast.If) and isinstance(child.test, ast.Compare):
                left = child.test.left
                if isinstance(left, ast.Name) and left.id == "platform_name" and child.test.comparators:
                    comp = child.test.comparators[0]
                    if isinstance(comp, ast.Constant) and comp.value in {"Gumroad", "Payhip"}:
                        branches[comp.value] = ast.get_source_segment(source, child) or ""
        self.assertIn("Gumroad", branches)
        self.assertIn("Payhip", branches)
        for platform, segment in branches.items():
            self.assertIn('"author": author', segment, f"{platform} must pass the author to the quality gate")

    def test_platform_builder_status_matches_quality_gate(self):
        source = FACTORY_PATH.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(FACTORY_PATH))
        nodes = {
            node.name: node for node in tree.body
            if isinstance(node, ast.FunctionDef) and node.name in {
                "v30_listing_content_audit", "v29_listing_quality_gate", "v22_build_platform_listing"
            }
        }
        self.assertEqual(set(nodes), {"v30_listing_content_audit", "v29_listing_quality_gate", "v22_build_platform_listing"})
        import datetime
        import tempfile

        with tempfile.TemporaryDirectory() as temp:
            master = pathlib.Path(temp) / "MASTER.pdf"
            master.write_bytes(b"test placeholder")
            namespace = {
                "Path": pathlib.Path,
                "re": re,
                "datetime": datetime.datetime,
                "FACTORY_VERSION": "30.0",
                "GUMROAD_DEFAULT_LICENSE": "Personal use only.",
                "_gl_clean_list": lambda value: list(value or []),
                "find_master_pdf": lambda project: master,
                "pdf_page_count": lambda path: 64,
                "inspect_pdf": lambda path: {"sizes": [{"width": 8.5, "height": 11}]},
                "_gl_num": lambda value: str(value),
                "_platform_cover": lambda project: None,
                "load_platform_profiles": lambda: {"Payhip": {"enabled": True}},
            }
            audit_module = ast.Module(body=[nodes["v30_listing_content_audit"]], type_ignores=[])
            exec(compile(audit_module, "<listing-audit>", "exec"), namespace)
            helper_module = ast.Module(body=[nodes["v29_listing_quality_gate"]], type_ignores=[])
            exec(compile(helper_module, "<listing-gate>", "exec"), namespace)
            builder_module = ast.Module(body=[nodes["v22_build_platform_listing"]], type_ignores=[])
            exec(compile(builder_module, "<listing-builder>", "exec"), namespace)
            project = pathlib.Path(temp)
            incomplete = namespace["v22_build_platform_listing"](
                project, "Payhip",
                {"title": "Test Book", "author": "J.A.C.",
                 "description": "A verified description.", "keywords": [],
                 "license_terms": "Personal use only."},
            )
            self.assertEqual(incomplete["quality_gate"]["status"], "NEEDS_INPUT")
            self.assertEqual(incomplete["status"], "REVIEW")
            complete = namespace["v22_build_platform_listing"](
                project, "Payhip",
                {"title": "Test Book", "author": "J.A.C.",
                 "description": "A verified description.", "keywords": ["horror"],
                 "license_terms": "Personal use only."},
            )
            self.assertEqual(complete["quality_gate"]["status"], "READY_FOR_REVIEW")
            self.assertEqual(complete["status"], "READY_FOR_REVIEW")

    def test_all_platform_listing_builder_writes_consistent_drafts_and_readiness_report(self):
        source = FACTORY_PATH.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(FACTORY_PATH))
        wanted = {
            "v30_listing_content_audit",
            "v29_listing_quality_gate",
            "v22_listing_text",
            "v22_build_platform_listing",
            "v22_build_all_platform_listings",
        }
        nodes = [node for node in tree.body
                 if isinstance(node, ast.FunctionDef) and node.name in wanted]
        self.assertEqual({node.name for node in nodes}, wanted)

        class FixedDateTime:
            @staticmethod
            def now():
                return datetime_module.datetime(2026, 10, 12, 12, 0, 0)

        def save_json(path, value):
            path = pathlib.Path(path)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(value, indent=2), encoding="utf-8")

        with tempfile.TemporaryDirectory() as temp:
            project = pathlib.Path(temp) / "Nightmare Cryptids"
            project.mkdir()
            master = project / "MASTER.pdf"
            master.write_bytes(b"verified master placeholder")
            profiles = {
                "KDP": {"enabled": True, "output_dir": "KDP"},
                "Gumroad": {"enabled": True, "output_dir": "GUMROAD"},
                "Payhip": {"enabled": True, "output_dir": "PAYHIP"},
                "Digital PDF": {"enabled": True, "output_dir": "DIGITAL_PDF"},
            }
            settings = {
                "title": "Nightmare Cryptids", "author": "J.A.C.",
                "description": "A horror coloring adventure.", "keywords": ["horror", "coloring"],
                "license_terms": "Personal use only.", "subtitle": "A Horror Coloring Adventure",
            }
            namespace = {
                "Path": pathlib.Path,
                "re": re,
                "datetime": FixedDateTime,
                "FACTORY_VERSION": "30.0",
                "MARKETING_DIR_NAME": "MARKETING",
                "GUMROAD_DEFAULT_LICENSE": "Personal use only.",
                "_gl_clean_list": lambda value: list(value or []),
                "_gl_num": lambda value: str(value),
                "_gl_first_sentences": lambda value, limit: str(value)[:limit],
                "_platform_cover": lambda project: None,
                "_platform_sanitized_filename": lambda value, limit: str(value).replace(" ", "_")[:limit],
                "find_master_pdf": lambda project: master,
                "pdf_page_count": lambda path: 64,
                "inspect_pdf": lambda path: {"sizes": [{"width": 8.5, "height": 11}]},
                "load_platform_profiles": lambda: profiles,
                "load_project_settings_safe": lambda project: settings,
                "gumroad_build_listing": lambda project, settings: {
                    "name": settings["title"], "price": 799, "summary": "Horror coloring book",
                    "description": settings["description"], "tags": settings["keywords"],
                    "details": [("Format", "PDF")], "files": [], "warnings": [],
                },
                "gumroad_load_overrides": lambda project: {"content_note": "", "license": "Personal use only."},
                "save_json": save_json,
            }
            exec(compile(ast.Module(body=nodes, type_ignores=[]), "<listing-batch-runtime>", "exec"), namespace)
            report = namespace["v22_build_all_platform_listings"](project)

            self.assertEqual(report["listing_count"], 4)
            self.assertEqual(report["ready_for_review"], 4)
            self.assertEqual(report["review"], 0)
            self.assertEqual(report["blocked"], 0)
            self.assertIn("nothing was uploaded or published", report["note"].lower())
            readiness_path = project / "MARKETING" / "LISTINGS" / "LISTING_READINESS.json"
            self.assertTrue(readiness_path.is_file())
            saved_report = json.loads(readiness_path.read_text(encoding="utf-8"))
            self.assertEqual(saved_report["listing_count"], 4)
            for platform in ("KDP", "Gumroad", "Payhip", "Digital PDF"):
                folder = project / "MARKETING" / "LISTINGS" / platform.replace(" ", "_")
                json_path = folder / "LISTING.json"
                text_path = folder / "LISTING.txt"
                self.assertTrue(json_path.is_file(), platform)
                self.assertTrue(text_path.is_file(), platform)
                data = json.loads(json_path.read_text(encoding="utf-8"))
                self.assertEqual(data["quality_gate"]["status"], "READY_FOR_REVIEW", platform)
                self.assertFalse(data["published"], platform)
                self.assertIn("not uploaded or published", data["note"].lower())

    def test_missing_master_blocks_release_without_guessing(self):
        result = self.gate(
            "Digital PDF",
            {"product_title": "Test", "full_description": "Details", "author": "JAC",
             "keywords": ["horror"], "license_terms": "Personal use"},
            master_exists=False, cover_exists=False, profile_enabled=True,
        )
        self.assertEqual(result["status"], "BLOCKED")
        self.assertIn("master_pdf", result["missing_required"])
        self.assertEqual(result["user_actions"][0]["key"], "price")
        self.assertFalse(result["published"])

    def test_blank_required_fields_are_actionable(self):
        result = self.gate(
            "Payhip", {"product_name": "Book", "price": ""},
            master_exists=True, cover_exists=True, profile_enabled=True,
        )
        self.assertEqual(result["status"], "NEEDS_INPUT")
        self.assertIn("description", result["missing_required"])
        self.assertIn("author", result["missing_required"])
        self.assertIn("keywords", result["missing_required"])
        self.assertIn("license", result["missing_required"])
        self.assertEqual(result["user_actions"][0]["key"], "price")

    def test_kdp_price_and_categories_remain_explicit_user_actions(self):
        fields = {
            "book_title": "Test Book",
            "description": "Verified details.",
            "author": "J.A.C.",
            "keywords": ["horror"],
            "print_options": {"page_count": 64},
        }
        result = self.gate(
            "KDP", fields, master_exists=True, cover_exists=True, profile_enabled=True
        )
        self.assertEqual(result["status"], "READY_FOR_REVIEW")
        self.assertEqual([item["key"] for item in result["user_actions"]], ["price", "categories"])

    def test_disabled_profile_is_visible_and_never_claims_publication(self):
        fields = {"product_title": "Test", "full_description": "Details",
                  "author": "JAC", "keywords": ["horror"], "license_terms": "Personal"}
        result = self.gate(
            "Digital PDF", fields, master_exists=True, cover_exists=False, profile_enabled=False
        )
        self.assertEqual(result["status"], "READY_FOR_REVIEW")
        profile = next(item for item in result["checks"] if item["key"] == "platform_profile")
        self.assertEqual(profile["status"], "RECOMMENDED")
        self.assertIn("disabled", profile["note"].lower())
        self.assertFalse(result["published"])


class PublishingContentAuditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        source = FACTORY_PATH.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(FACTORY_PATH))
        node = next((item for item in tree.body
                    if isinstance(item, ast.FunctionDef) and item.name == "v30_listing_content_audit"), None)
        if node is None:
            raise AssertionError("v30_listing_content_audit must exist exactly once")
        namespace = {"re": re}
        exec(compile(ast.Module(body=[node], type_ignores=[]), str(FACTORY_PATH), "exec"), namespace)
        cls.audit = staticmethod(namespace["v30_listing_content_audit"])

    def test_digital_listing_flags_physical_fulfillment_language(self):
        result = self.audit("Gumroad", {
            "name": "Nightmare Book",
            "description": "A paperback coloring book shipped directly to your door.",
            "price": "$7.99",
            "tags": ["horror"],
        })
        self.assertEqual(result["status"], "REVIEW_WARNINGS")
        self.assertIn("digital_physical_language", [item["key"] for item in result["issues"]])

    def test_invalid_price_requires_correction_without_guessing(self):
        result = self.audit("Payhip", {"name": "Book", "price": "-4.00"})
        self.assertEqual(result["status"], "NEEDS_CORRECTION")
        self.assertEqual(result["error_count"], 1)
        self.assertIn("invalid_price", [item["key"] for item in result["issues"]])

    def test_kdp_keyword_limit_and_duplicates_are_reported(self):
        result = self.audit("KDP", {"book_title": "Book"}, [
            "horror", "Horror", "cryptids", "coloring", "monsters", "dark art",
            "printable", "adult coloring", "a" * 51,
        ])
        keys = [item["key"] for item in result["issues"]]
        self.assertIn("duplicate_keywords", keys)
        self.assertIn("kdp_keyword_count", keys)
        self.assertIn("kdp_keyword_length", keys)

    def test_clean_digital_listing_passes_and_is_not_rewritten(self):
        fields = {"name": "Nightmare Book", "description": "A digital PDF coloring book.",
                  "price": "$7.99", "tags": ["horror", "cryptids"]}
        result = self.audit("Gumroad", fields)
        self.assertEqual(result["status"], "PASS")
        self.assertIn("No listing text", result["note"])
        self.assertEqual(fields["price"], "$7.99")


if __name__ == "__main__":
    unittest.main()
