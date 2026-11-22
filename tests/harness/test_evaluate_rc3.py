import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]


def load_module():
    spec = importlib.util.spec_from_file_location(
        "evaluate_rc3", ROOT / "scripts" / "evaluate_rc3.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class EvaluateRc3Tests(unittest.TestCase):
    def test_deterministic_modes_separate_evidence_classes(self):
        module = load_module()
        with tempfile.TemporaryDirectory() as tmp:
            report = Path(tmp) / "rc3.json"
            self.assertEqual(module.main(["--mode", "all", "--report", str(report)]), 0)
            data = json.loads(report.read_text(encoding="utf-8"))

        self.assertEqual(data["modes"], ["fixture", "reference"])
        self.assertEqual(len(data["cases"]), 8)
        self.assertTrue(all(item["evidence_class"] == "deterministic_fixture" for item in data["cases"]))
        self.assertTrue(all(item["business_outcome"] == "not_measured" for item in data["cases"]))
        self.assertEqual(data["summary"]["error_cases"], 0)
        self.assertEqual(data["summary"]["stage_failures"], 0)
        self.assertEqual(data["summary"]["real_model_execution"], {"status": "not_run", "calls": 0})
        self.assertEqual(data["summary"]["cost"]["status"], "not_incurred")
        self.assertLess(
            data["summary"]["quality_by_mode"]["fixture"],
            data["summary"]["quality_by_mode"]["reference"],
        )

    def test_model_mode_requires_model_name(self):
        module = load_module()
        with self.assertRaises(SystemExit):
            module.main(["--mode", "model", "--report", "/tmp/unused.json"])


if __name__ == "__main__":
    unittest.main()
