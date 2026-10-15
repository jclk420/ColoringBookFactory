"""Source integration checks for the publishing completion menu."""
import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SOURCE = (ROOT / "factory.py").read_text(encoding="utf-8")

class PublishingCompletionMenuTests(unittest.TestCase):
    def test_version_and_menu_option_are_wired(self):
        self.assertIn('FACTORY_VERSION = "102.0"', SOURCE)
        self.assertIn('31. Publishing Completion Center', SOURCE)
        self.assertIn('elif c=="31": v102_publishing_completion_menu()', SOURCE)

    def test_menu_function_is_defined_once_and_report_is_non_destructive(self):
        self.assertEqual(SOURCE.count("def v102_publishing_completion_menu("), 1)
        self.assertIn("write_report_no_clobber(project, report)", SOURCE)
        self.assertIn("Nothing was uploaded or published.", SOURCE)

if __name__ == "__main__":
    unittest.main(verbosity=2)
