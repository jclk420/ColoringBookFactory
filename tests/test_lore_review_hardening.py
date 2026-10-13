import ast
import difflib
import re
import unittest
from pathlib import Path

FACTORY_PATH = Path(__file__).resolve().parents[1] / "factory.py"


class LoreReviewHardeningTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        source = FACTORY_PATH.read_text(encoding="utf-8")
        tree = ast.parse(source)
        functions = [node for node in tree.body
                     if isinstance(node, ast.FunctionDef) and node.name == "lore_intake_quality_audit"]
        if len(functions) != 1:
            raise AssertionError("Expected one lore_intake_quality_audit function")
        namespace = {"re": re, "difflib": difflib}
        exec(compile(ast.Module(body=functions, type_ignores=[]), str(FACTORY_PATH), "exec"), namespace)
        cls.audit = staticmethod(namespace["lore_intake_quality_audit"])

    def test_unknown_confidence_is_flagged_without_rewriting_record(self):
        record = {"file": "scan.pdf", "confidence": "ABSOLUTE"}
        result = self.audit([record], {"entities": [], "relationships": []})
        self.assertEqual(result["confidence_findings"][0]["type"], "unknown_confidence_label")
        self.assertEqual(record["confidence"], "ABSOLUTE")

    def test_duplicate_page_references_are_flagged_across_records(self):
        result = self.audit(
            [{"file": "scan.pdf", "source_pages": [2, "2", 3]}],
            {"entities": [{"name": "Ghoul", "source_pages": [4, 4]}],
             "relationships": [{"subject": "Ghoul", "relation": "haunts", "object": "Cell", "source_pages": [7, 7]}]})
        self.assertEqual(len(result["repeated_page_findings"]), 3)

    def test_duplicate_aliases_and_malformed_alias_type_are_flagged(self):
        result = self.audit([], {"entities": [
            {"name": "Ash Maw", "aliases": ["The Maw", "the-maw"]},
            {"name": "Bog Thing", "aliases": "Bog Beast"}], "relationships": []})
        kinds = {row["type"] for row in result["duplicate_alias_findings"]}
        self.assertIn("duplicate_alias_within_entity", kinds)
        self.assertIn("aliases_wrong_type", kinds)

    def test_relationships_without_provenance_are_flagged(self):
        result = self.audit([], {"entities": [], "relationships": [
            {"subject": "Ash Maw", "relation": "guards", "object": "Gate"}]})
        finding = result["relationship_provenance_findings"][0]
        self.assertEqual(set(finding["missing"]), {"source file", "evidence", "source page"})

    def test_duplicate_relationships_are_flagged_but_not_removed(self):
        links = [
            {"subject": "Ash Maw", "relation": "guards", "object": "Gate", "source_files": ["a.pdf"]},
            {"subject": "ash-maw", "relation": "GUARDS", "object": "gate", "source_files": ["b.pdf"]}]
        result = self.audit([], {"entities": [], "relationships": links})
        self.assertEqual(result["duplicate_relationship_findings"][0]["count"], 2)
        self.assertEqual(len(links), 2)
        self.assertFalse(result["canon_written"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
