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


class LifecycleTests(unittest.TestCase):
    def setUp(self):
        from bot.database import Database
        self.db = Database(os.path.join(tempfile.mkdtemp(), "life.db"))

    def test_first_start_is_not_unclean(self):
        from bot.services.lifecycle import mark_started
        self.assertFalse(mark_started(self.db))

    def test_clean_shutdown_then_start(self):
        from bot.services.lifecycle import mark_started, mark_clean_shutdown
        mark_started(self.db)
        mark_clean_shutdown(self.db)
        self.assertFalse(mark_started(self.db))

    def test_crash_then_start_is_unclean(self):
        from bot.services.lifecycle import mark_started
        mark_started(self.db)          # çalışırken çöktü: kapanış işareti yazılmadı
        self.assertTrue(mark_started(self.db))
        self.assertTrue(mark_started(self.db), "her kirli açılış tekrar raporlanır")


class VersionTests(unittest.TestCase):
    def test_env_wins(self):
        from bot.services.lifecycle import resolve_version
        self.assertEqual(resolve_version(env={"BOT_VERSION": "abc1234"}, version_file="/yok", git=lambda: "x"), "abc1234")

    def test_version_file(self):
        from bot.services.lifecycle import resolve_version
        path = os.path.join(tempfile.mkdtemp(), "version")
        with open(path, "w") as f:
            f.write("def5678\n")
        self.assertEqual(resolve_version(env={}, version_file=path, git=lambda: "x"), "def5678")

    def test_empty_version_file_falls_back_to_git(self):
        from bot.services.lifecycle import resolve_version
        path = os.path.join(tempfile.mkdtemp(), "version")
        open(path, "w").close()
        self.assertEqual(resolve_version(env={}, version_file=path, git=lambda: "9a9a9a9"), "9a9a9a9")

    def test_everything_missing_is_dev(self):
        from bot.services.lifecycle import resolve_version

        def broken_git():
            raise OSError("git yok")
        self.assertEqual(resolve_version(env={}, version_file="/yok/version", git=broken_git), "dev")


if __name__ == "__main__":
    unittest.main()
