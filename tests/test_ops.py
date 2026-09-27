"""Operasyon modülleri testleri (config, lifecycle, admin bildirimleri, heartbeat). Ağ kullanmaz."""
import asyncio
import os
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("BOT_DATABASE_PATH", os.path.join(tempfile.mkdtemp(), "ops_test.db"))


class RequireBotTokenTests(unittest.TestCase):
    def test_missing_token_raises_clear_error(self):
        from bot import config
        with mock.patch.dict(os.environ, {"BOT_TOKEN": ""}):
            with self.assertRaises(RuntimeError) as ctx:
                config.require_bot_token()
        self.assertIn("BOT_TOKEN", str(ctx.exception))

    def test_whitespace_only_token_is_rejected(self):
        from bot import config
        with mock.patch.dict(os.environ, {"BOT_TOKEN": "   "}):
            with self.assertRaises(RuntimeError):
                config.require_bot_token()

    def test_token_is_trimmed_and_unquoted(self):
        from bot import config
        with mock.patch.dict(os.environ, {"BOT_TOKEN": ' "123:ABC" '}):
            self.assertEqual(config.require_bot_token(), "123:ABC")


if __name__ == "__main__":
    unittest.main()
