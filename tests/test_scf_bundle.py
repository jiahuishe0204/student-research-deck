import json
from pathlib import Path
import tempfile
import unittest
import zipfile

from scripts.build_scf_bundle import REQUIRED, build


class ScfBundleTests(unittest.TestCase):
    def test_bundle_contains_current_entrypoints_and_no_local_data(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            dependency = root / "deps" / "example_dependency"
            dependency.mkdir(parents=True)
            (dependency / "__init__.py").write_text("VERSION = 1\n")
            output = root / "candidate.zip"
            build(root / "deps", output)
            with zipfile.ZipFile(output) as archive:
                names = set(archive.namelist())
                self.assertTrue(REQUIRED.issubset(names))
                self.assertIn("example_dependency/__init__.py", names)
                self.assertFalse(any(name.startswith(("data/", "tests/", ".git/")) for name in names))
                self.assertFalse(any(name.endswith((".db", ".zip")) for name in names))
                manifest = json.loads(archive.read("bundle-manifest.json"))
                self.assertIn("intent_http_entrypoint.py", manifest["source_sha256"])
                self.assertEqual(len(manifest["source_commit"]), 40)


if __name__ == "__main__": unittest.main()
