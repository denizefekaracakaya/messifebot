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


# Helpers for Task 3 and Task 4 tests
class FakeBot:
    def __init__(self, fail=False):
        self.sent = []
        self.fail = fail
        self.get_me_calls = 0

    async def send_message(self, chat_id, text, **kwargs):
        if self.fail:
            raise RuntimeError("Forbidden: bot was blocked by the user")
        self.sent.append((chat_id, text, kwargs.get("parse_mode")))

    async def get_me(self):
        self.get_me_calls += 1
        if self.fail:
            raise RuntimeError("Telegram'a ulaşılamadı")
        return object()


class Clock:
    def __init__(self):
        self.t = 1_000_000.0

    def __call__(self):
        return self.t


def run(coro):
    return asyncio.run(coro)


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


class AdminNotifierTests(unittest.TestCase):
    def test_no_admins_sends_nothing(self):
        from bot.services.admin_notify import AdminNotifier
        bot = FakeBot()
        notifier = AdminNotifier(bot, [])
        self.assertFalse(notifier.enabled)
        self.assertFalse(run(notifier.notify_startup("abc", False)))
        self.assertFalse(run(notifier.notify_error("KeyError", "komut /portfolio")))
        self.assertEqual(bot.sent, [])

    def test_startup_message_to_every_admin(self):
        from bot.services.admin_notify import AdminNotifier
        bot = FakeBot()
        self.assertTrue(run(AdminNotifier(bot, [1, 2]).notify_startup("abc1234", False)))
        self.assertEqual([s[0] for s in bot.sent], [1, 2])
        self.assertIn("abc1234", bot.sent[0][1])
        self.assertNotIn("düzgün kapanmadı", bot.sent[0][1])
        self.assertEqual(bot.sent[0][2], "HTML")

    def test_unclean_note(self):
        from bot.services.admin_notify import AdminNotifier
        bot = FakeBot()
        run(AdminNotifier(bot, [1]).notify_startup("v", True))
        self.assertIn("düzgün kapanmadı", bot.sent[0][1])

    def test_values_are_html_escaped(self):
        from bot.services.admin_notify import AdminNotifier
        bot = FakeBot()
        notifier = AdminNotifier(bot, [1])
        run(notifier.notify_startup("<b>x</b>", False))
        run(notifier.notify_error("Err<&>", "komut /a<b>"))
        for _, text, _ in bot.sent:
            self.assertNotIn("<b>x", text)
            self.assertNotIn("Err<&>", text)
        self.assertIn("&lt;b&gt;x", bot.sent[0][1])

    def test_send_failure_is_swallowed(self):
        from bot.services.admin_notify import AdminNotifier
        notifier = AdminNotifier(FakeBot(fail=True), [1])
        self.assertFalse(run(notifier.notify_startup("v", False)))
        self.assertFalse(run(notifier.notify_error("KeyError", "genel")))

    def test_same_error_limited_to_once_per_30_minutes(self):
        from bot.services.admin_notify import AdminNotifier
        bot, clock = FakeBot(), Clock()
        notifier = AdminNotifier(bot, [1], clock=clock)
        self.assertTrue(run(notifier.notify_error("KeyError", "komut /portfolio")))
        clock.t += 29 * 60
        self.assertFalse(run(notifier.notify_error("KeyError", "komut /portfolio")))
        self.assertTrue(run(notifier.notify_error("KeyError", "komut /alert")), "farklı yer ayrı sayılır")
        clock.t += 2 * 60
        self.assertTrue(run(notifier.notify_error("KeyError", "komut /portfolio")))

    def test_hourly_cap_of_10(self):
        from bot.services.admin_notify import AdminNotifier
        bot, clock = FakeBot(), Clock()
        notifier = AdminNotifier(bot, [1], clock=clock)
        results = [run(notifier.notify_error(f"E{i}", "genel")) for i in range(12)]
        self.assertEqual(results.count(True), 10)
        clock.t += 3601
        self.assertTrue(run(notifier.notify_error("E99", "genel")))


if __name__ == "__main__":
    unittest.main()
