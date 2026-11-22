import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("privacy_scan", ROOT / "scripts" / "privacy_scan.py")
privacy_scan = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(privacy_scan)


class PrivacyScanEmailRules(unittest.TestCase):
    def test_reserved_local_domains_are_not_contacts(self):
        for value in ("nextvariable@trae.local", "user@host.localhost", "bot@ci.internal"):
            self.assertEqual(privacy_scan.findings(value.encode()), [], value)

    def test_public_domains_are_still_flagged(self):
        hits = privacy_scan.findings(b"owner@real-company.com")
        self.assertEqual(hits, [{"rule": "email", "matches": 1}])

    def test_noreply_and_example_domains_are_ignored(self):
        for value in (
            "someone@users.noreply.github.com",
            "git@github.com",
            "person@example.org",
        ):
            self.assertEqual(privacy_scan.findings(value.encode()), [], value)


if __name__ == "__main__":
    unittest.main()
