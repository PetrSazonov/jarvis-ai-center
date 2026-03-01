import os
import unittest
from unittest.mock import patch

from core.settings import load_settings


class SettingsTests(unittest.TestCase):
    def _base_env(self) -> dict[str, str]:
        return {
            "BOT_TOKEN": "test-token",
            "DIGEST_TIMES": "07:00,14:00,21:00",
        }

    def test_soft_timeout_default(self):
        env = self._base_env()
        with patch.dict(os.environ, env, clear=True):
            settings = load_settings()
        self.assertEqual(settings.ollama_soft_timeout_seconds, 25.0)

    def test_soft_timeout_custom(self):
        env = self._base_env()
        env["OLLAMA_SOFT_TIMEOUT_SECONDS"] = "45"
        with patch.dict(os.environ, env, clear=True):
            settings = load_settings()
        self.assertEqual(settings.ollama_soft_timeout_seconds, 45.0)

    def test_soft_timeout_too_low_raises(self):
        env = self._base_env()
        env["OLLAMA_SOFT_TIMEOUT_SECONDS"] = "3"
        with patch.dict(os.environ, env, clear=True):
            with self.assertRaises(RuntimeError):
                load_settings()


if __name__ == "__main__":
    unittest.main()

