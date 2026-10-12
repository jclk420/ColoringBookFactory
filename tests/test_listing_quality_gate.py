"""Regression tests for the v29 platform listing quality gate."""
import ast
import pathlib
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


if __name__ == "__main__":
    unittest.main()
