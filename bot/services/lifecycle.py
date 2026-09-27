# bot/services/lifecycle.py
"""Çalışma yaşam döngüsü: temiz kapanış işareti ve çalışan sürümün tespiti."""
import os
import subprocess
from typing import Callable, Mapping

from bot.config import BASE_DIR, VERSION_FILE

CLEAN_SHUTDOWN_KEY = "clean_shutdown"


def mark_started(db) -> bool:
    """Açılışta çağrılır. Önceki çalışma düzgün kapanmadıysa True döner.

    İlk kurulumda (anahtar hiç yoksa) False döner.
    """
    previous = db.get_meta(CLEAN_SHUTDOWN_KEY)
    db.set_meta(CLEAN_SHUTDOWN_KEY, "0")
    return previous == "0"


def mark_clean_shutdown(db) -> None:
    """Düzgün kapanışta (post_shutdown) çağrılır."""
    db.set_meta(CLEAN_SHUTDOWN_KEY, "1")


def _git_short_head() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"], cwd=BASE_DIR,
        capture_output=True, text=True, timeout=5, check=True,
    )
    return result.stdout.strip()


def resolve_version(env: Mapping[str, str] = os.environ, version_file: str = VERSION_FILE,
                    git: Callable[[], str] = _git_short_head) -> str:
    """Sıra: BOT_VERSION ortam değişkeni -> sürüm dosyası -> git kısa hash -> 'dev'."""
    version = (env.get("BOT_VERSION") or "").strip()
    if version:
        return version
    try:
        with open(version_file, encoding="utf-8") as f:
            version = f.read().strip()
        if version:
            return version
    except OSError:
        pass
    try:
        version = git()
        if version:
            return version
    except Exception:
        pass
    return "dev"
