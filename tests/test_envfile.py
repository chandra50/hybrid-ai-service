import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from hybrid_ai.envfile import env_file, load_env_file


class EnvFile(unittest.TestCase):
    def _write(self, text):
        d = tempfile.mkdtemp()
        p = Path(d) / "env"
        p.write_text(text)
        return p

    def test_loads_values_and_returns_only_names(self):
        p = self._write('# comment\nexport HYB_TEST_A="quoted value"\nHYB_TEST_B=\'single\'\n\nnot a setting\nHYB_TEST_EMPTY=\n')
        with mock.patch.dict(os.environ, {"HYBRID_ENV_FILE": str(p)}, clear=False):
            for k in ("HYB_TEST_A", "HYB_TEST_B", "HYB_TEST_EMPTY"):
                os.environ.pop(k, None)
            names = load_env_file()
            self.assertEqual(names, ["HYB_TEST_A", "HYB_TEST_B"])
            self.assertEqual(os.environ["HYB_TEST_A"], "quoted value")
            self.assertEqual(os.environ["HYB_TEST_B"], "single")
            self.assertNotIn("HYB_TEST_EMPTY", os.environ)
            for k in names:
                os.environ.pop(k)

    def test_environment_wins(self):
        p = self._write("HYB_TEST_C=from-file\n")
        with mock.patch.dict(os.environ, {"HYBRID_ENV_FILE": str(p), "HYB_TEST_C": "from-env"}):
            self.assertEqual(load_env_file(), [])
            self.assertEqual(os.environ["HYB_TEST_C"], "from-env")

    def test_missing_file_is_fine(self):
        with mock.patch.dict(os.environ, {"HYBRID_ENV_FILE": "/nonexistent/hybrid-ai/env"}):
            self.assertEqual(env_file(), Path("/nonexistent/hybrid-ai/env"))
            self.assertEqual(load_env_file(), [])


if __name__ == "__main__":
    unittest.main()
