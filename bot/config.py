# bot/config.py
import os
from dotenv import load_dotenv

# telegram-bot/ dizini
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

load_dotenv(os.path.join(BASE_DIR, ".env"))

# Bot ayarları
def require_bot_token() -> str:
    """BOT_TOKEN'ı ortamdan okur; yoksa açık bir hata verir (koda gömülü varsayılan token yoktur)."""
    token = (os.getenv("BOT_TOKEN") or "").strip().strip('"').strip("'").strip()
    if not token:
        raise RuntimeError(
            "BOT_TOKEN tanımlı değil. Yerelde telegram-bot/.env dosyasına, sunucuda "
            "/etc/messifebot.env dosyasına BOT_TOKEN=... satırını ekleyin."
        )
    return token

# Admin ID'leri .env içinde virgülle ayrılmış olarak: ADMIN_IDS=123456789,987654321
# Kendi ID'ni bota /id yazarak öğrenebilirsin
ADMIN_IDS = [int(x) for x in os.getenv("ADMIN_IDS", "").replace(" ", "").split(",") if x.isdigit()]

# API Key'ler (isteğe bağlı - ayarlı olmayan haber kaynakları atlanır)
NEWSAPI_KEY = os.getenv("NEWSAPI_KEY", "")
GNEWS_API_KEY = os.getenv("GNEWS_API_KEY", "")
NEWSDATA_API_KEY = os.getenv("NEWSDATA_API_KEY", "")
CRYPTOCOMPARE_API_KEY = os.getenv("CRYPTOCOMPARE_API_KEY", "")
ALPHA_VANTAGE_KEY = os.getenv("ALPHA_VANTAGE_KEY", "")

# Veritabanı ayarları
DATA_DIR = os.path.join(BASE_DIR, "data")
DATABASE_PATH = os.getenv("BOT_DATABASE_PATH") or os.path.join(DATA_DIR, "chat_stats.db")

# Sürüm bilgisi dosyası (sunucuda deploy.sh yazar)
VERSION_FILE = os.getenv("BOT_VERSION_FILE", "/var/lib/messifebot/version")

# healthchecks.io ping URL'si (boşsa dış kontrol kapalı)
HEALTHCHECK_URL = (os.getenv("HEALTHCHECK_URL") or "").strip()

# Varsayılan saat dilimi (raporlar için)
DEFAULT_TIMEZONE = "Europe/Istanbul"

# Diğer ayarlar
LOG_LEVEL = "INFO"

def create_directories():
    """Gerekli dizinleri oluştur"""
    os.makedirs(DATA_DIR, exist_ok=True)

# Dizinleri oluştur
create_directories()
