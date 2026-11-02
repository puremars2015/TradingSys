"""Offline checks for credential-free configuration defaults and examples."""
import os
from pathlib import Path
import runpy
import sys
import types
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
CREDENTIALS = (
    'SECRET_KEY', 'TELEGRAM_BOT_TOKEN', 'TELEGRAM_BOT_TOKEN_2',
    'OPENROUTER_API_KEY', 'AGNES_API_KEY',
    'LINE_CHANNEL_ACCESS_TOKEN', 'LINE_CHANNEL_SECRET',
)


class SecretConfigurationTests(unittest.TestCase):
    def load_config(self, environment):
        # Never load a real developer .env or contact an external service.
        dotenv = types.ModuleType('dotenv')
        dotenv.load_dotenv = lambda: None
        with patch.dict(os.environ, environment, clear=True), \
             patch.dict(sys.modules, {'dotenv': dotenv}), \
             patch('os.makedirs'):
            return runpy.run_path(str(ROOT / 'app/config.py'))['Config']

    def test_missing_credentials_have_no_hardcoded_fallback(self):
        config = self.load_config({})
        for name in CREDENTIALS + ('TELEGRAM_USER_ID', 'TELEGRAM_USER_ID_2'):
            with self.subTest(variable=name):
                self.assertEqual(getattr(config, name), '')

    def test_config_uses_provided_environment_values(self):
        values = {name: 'offline-test-placeholder' for name in CREDENTIALS}
        config = self.load_config(values)
        for name, value in values.items():
            with self.subTest(variable=name):
                self.assertEqual(getattr(config, name), value)

    def test_example_has_empty_credentials_and_both_bots(self):
        values = dict(line.split('=', 1) for line in
                      (ROOT / '.env.example').read_text().splitlines()
                      if line and not line.startswith('#') and '=' in line)
        for name in CREDENTIALS + ('CLOUDFLARE_TUNNEL_TOKEN',
                                  'TELEGRAM_USER_ID', 'TELEGRAM_USER_ID_2'):
            with self.subTest(variable=name):
                self.assertIn(name, values)
                self.assertEqual(values[name], '')

    def test_docker_context_excludes_git_and_local_env(self):
        rules = (ROOT / '.dockerignore').read_text().splitlines()
        for rule in ('.git', '.env', '.env.*', '!.env.example'):
            self.assertIn(rule, rules)


if __name__ == '__main__':
    unittest.main()
