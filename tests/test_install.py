import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
import subprocess

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/install.py"
SPEC = importlib.util.spec_from_file_location("installer", SCRIPT)
INSTALLER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(INSTALLER)


def fixture(name):
    return {
        "skill": name,
        "repository": f"https://github.com/NextVariable/{name}",
        "revision": "a" * 40,
        "path": f"skills/{name}",
    }


def fake_fetch(item, checkout):
    source = checkout / item["path"]
    source.mkdir(parents=True)
    (source / "SKILL.md").write_text(item["skill"], encoding="utf-8")
    (source / "LICENSE").write_text("test license", encoding="utf-8")
    return source


class InstallerTests(unittest.TestCase):
    def test_malformed_catalog_returns_a_clear_error(self):
        samples = [
            None,
            [],
            {"schema_version": True, "skills": []},
            {"schema_version": 1, "skills": [None]},
            {"schema_version": 1, "skills": [{"skill": 12}]},
        ]
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "catalog.json"
            for sample in samples:
                with self.subTest(sample=sample):
                    path.write_text(json.dumps(sample), encoding="utf-8")
                    with self.assertRaises(ValueError):
                        INSTALLER.load_catalog(path)

    def test_install_excludes_machine_generated_cache(self):
        def with_cache(item, checkout):
            source = fake_fetch(item, checkout)
            (source / "scripts/__pycache__").mkdir(parents=True)
            (source / "scripts/__pycache__/helper.pyc").write_bytes(b"local-machine-cache")
            (source / ".DS_Store").write_bytes(b"desktop-metadata")
            (source / "scripts/helper.py").write_text("print('ready')", encoding="utf-8")
            return source

        with tempfile.TemporaryDirectory() as temp:
            dest = Path(temp) / "target"
            INSTALLER.install([fixture("one")], dest, with_cache)
            self.assertTrue((dest / "one/scripts/helper.py").is_file())
            self.assertTrue((dest / "one/LICENSE").is_file())
            self.assertFalse((dest / "one/scripts/__pycache__").exists())
            self.assertFalse((dest / "one/.DS_Store").exists())

    def test_real_checkout_does_not_run_downloaded_hook(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            origin = root / "fixture.git"
            origin.mkdir()
            hooks = root / "trusted-fixture-hooks"
            hooks.mkdir()

            def git(*args):
                return subprocess.run(
                    ["git", "-C", str(origin), "-c", f"core.hooksPath={hooks}", *args],
                    check=True,
                    capture_output=True,
                    text=True,
                ).stdout.strip()

            git("init", "--quiet")
            git("config", "user.name", "Fixture")
            git("config", "user.email", "fixture@example.invalid")
            source = origin / "skills/one"
            source.mkdir(parents=True)
            (source / "SKILL.md").write_text("fixture", encoding="utf-8")
            (source / "LICENSE").write_text("fixture", encoding="utf-8")
            hostile = origin / ".empty-hooks/post-checkout"
            hostile.parent.mkdir()
            hostile.write_text(
                "#!/bin/sh\nprintf 'executed\\n' > executed-marker.txt\n", encoding="utf-8"
            )
            hostile.chmod(0o755)
            git("add", ".")
            git("update-index", "--chmod=+x", ".empty-hooks/post-checkout")
            git("-c", "commit.gpgsign=false", "commit", "--quiet", "-m", "fixture")
            item = fixture("one")
            item["repository"] = str(origin)[:-4]
            item["revision"] = git("rev-parse", "HEAD")
            checkout = root / "download"
            fetched = INSTALLER.fetch(item, checkout)
            self.assertTrue((fetched / "SKILL.md").is_file())
            self.assertFalse((checkout / "executed-marker.txt").exists())

    def test_select_unknown_is_error(self):
        with self.assertRaises(ValueError):
            INSTALLER.select([fixture("one")], ["missing"])

    def test_existing_directory_is_never_changed(self):
        with tempfile.TemporaryDirectory() as temp:
            dest = Path(temp)
            existing = dest / "one"
            existing.mkdir()
            (existing / "custom.md").write_text("keep")
            with self.assertRaises(ValueError):
                INSTALLER.install([fixture("one")], dest, fake_fetch)
            self.assertEqual((existing / "custom.md").read_text(), "keep")
            self.assertFalse((existing / "SKILL.md").exists())

    def test_failed_second_download_writes_nothing(self):
        def failing(item, checkout):
            if item["skill"] == "two":
                raise OSError("simulated offline")
            return fake_fetch(item, checkout)

        with tempfile.TemporaryDirectory() as temp:
            dest = Path(temp) / "target"
            with self.assertRaises(OSError):
                INSTALLER.install([fixture("one"), fixture("two")], dest, failing)
            self.assertFalse(dest.exists())

    def test_install_copies_only_complete_unit(self):
        with tempfile.TemporaryDirectory() as temp:
            dest = Path(temp) / "target"
            installed = INSTALLER.install([fixture("one"), fixture("two")], dest, fake_fetch)
            self.assertEqual(installed, ["one", "two"])
            self.assertEqual((dest / "one/SKILL.md").read_text(), "one")
            self.assertTrue((dest / "two/LICENSE").is_file())
            self.assertFalse((dest / ".git").exists())

    def test_reject_traversal_in_catalog(self):
        with tempfile.TemporaryDirectory() as temp:
            entries = [fixture(f"skill-{i}") for i in range(5)]
            entries[0]["path"] = "../escape"
            path = Path(temp) / "catalog.json"
            path.write_text(json.dumps({"schema_version": 1, "skills": entries}))
            with self.assertRaisesRegex(ValueError, "unexpected install path"):
                INSTALLER.load_catalog(path)

    def test_missing_license_never_installs(self):
        def incomplete(item, checkout):
            source = fake_fetch(item, checkout)
            (source / "LICENSE").unlink()
            return source

        with tempfile.TemporaryDirectory() as temp:
            dest = Path(temp) / "target"
            with self.assertRaises(ValueError):
                INSTALLER.install([fixture("one")], dest, incomplete)
            self.assertFalse(dest.exists())


if __name__ == "__main__":
    unittest.main()
