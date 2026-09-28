# bot/services/real_news_service.py
import re
import time
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import requests

from bot.config import (
    NEWSAPI_KEY, GNEWS_API_KEY, NEWSDATA_API_KEY, CRYPTOCOMPARE_API_KEY, DEFAULT_TIMEZONE
)

TOPIC_QUERIES = {
    'markets': 'borsa OR hisse OR BIST OR dolar OR "altın fiyatları" OR "gram altın"',
    'economy': 'ekonomi OR enflasyon OR faiz OR "merkez bankası"',
    'crypto': 'bitcoin OR kripto OR ethereum OR blockchain',
}


def _is_configured(key: str) -> bool:
    """Boş veya şablon ('your_..._here') anahtarları yok say"""
    return bool(key) and not key.startswith('your_')


class RealNewsService:
    """Gerçek haber API'lerinden haber çeker.

    Anahtarı tanımlı olan kaynaklar sırayla denenir. Hiçbiri sonuç vermezse
    boş liste döner — sahte/örnek haber üretilmez.
    """

    def __init__(self):
        self.cache = {}
        self.cache_timeout = 300  # 5 dakika cache
        self.tz = ZoneInfo(DEFAULT_TIMEZONE)

    # --- Yardımcılar -------------------------------------------------------

    def _format_date(self, value=None):
        """API tarihini (ISO metni veya unix timestamp) yerel saatle formatla"""
        try:
            if value is None or value == '':
                dt = datetime.now(timezone.utc)
            elif isinstance(value, (int, float)):
                dt = datetime.fromtimestamp(value, tz=timezone.utc)
            else:
                dt = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(self.tz).strftime('%d.%m.%Y %H:%M')
        except (ValueError, OSError):
            return str(value)

    def _cached(self, key, fetch):
        entry = self.cache.get(key)
        if entry and time.time() - entry[0] < self.cache_timeout:
            return entry[1]
        result = fetch()
        if result:
            self.cache[key] = (time.time(), result)
        return result

    def _clean_description(self, description):
        """HTML etiketlerini temizle ve kısalt"""
        if not description:
            return ""
        cleaned = re.sub(r'<.*?>', '', description).strip()
        if len(cleaned) > 200:
            return cleaned[:200].rsplit(' ', 1)[0] + "..."
        return cleaned

    def _determine_importance(self, title):
        """Başlığa göre önem seviyesi belirle"""
        important_keywords = ['kriz', 'faiz', 'merkez bankası', 'dolar', 'euro', 'altın', 'bist', 'kripto', 'bitcoin', 'acil', 'önemli']
        title_lower = (title or '').lower()
        return 'high' if any(k in title_lower for k in important_keywords) else 'medium'

    def _item(self, title, description, source, published, url):
        return {
            'title': title or '',
            'description': self._clean_description(description),
            'source': source or '',
            'published_at': self._format_date(published),
            'importance': self._determine_importance(title),
            'url': url or '',
        }

    # --- Finans / ekonomi haberleri ----------------------------------------

    def get_financial_news(self, topic='markets'):
        """Finans ('markets') veya ekonomi ('economy') haberlerini getir.
        Bloklayan çağrı - handler'larda asyncio.to_thread ile kullanın."""
        return self._cached(f'fin:{topic}', lambda: self._fetch_financial(topic)) or []

    def _fetch_financial(self, topic):
        query = TOPIC_QUERIES.get(topic, TOPIC_QUERIES['markets'])
        providers = [
            (NEWSAPI_KEY, self._get_newsapi_news),
            (GNEWS_API_KEY, self._get_gnews_news),
            (NEWSDATA_API_KEY, self._get_newsdata_news),
        ]
        for key, provider in providers:
            if not _is_configured(key):
                continue
            news = provider(query, key)
            if news:
                return news
        return []

    def _get_newsapi_news(self, query, key):
        """NewsAPI.org"""
        try:
            response = requests.get(
                "https://newsapi.org/v2/everything",
                params={'q': query, 'searchIn': 'title', 'language': 'tr', 'sortBy': 'publishedAt', 'pageSize': 8},
                headers={'X-Api-Key': key},
                timeout=10,
            )
            if response.status_code != 200:
                print(f"❌ NewsAPI hatası: {response.status_code} {response.text[:200]}")
                return None
            return [
                self._item(a.get('title'), a.get('description'), (a.get('source') or {}).get('name', 'NewsAPI'),
                           a.get('publishedAt'), a.get('url'))
                for a in response.json().get('articles', [])[:6]
                if a.get('title') and a.get('title') != '[Removed]'
            ]
        except Exception as e:
            print(f"❌ NewsAPI hatası: {e}")
            return None

    def _get_gnews_news(self, query, key):
        """GNews API"""
        try:
            response = requests.get(
                "https://gnews.io/api/v4/search",
                params={'q': query, 'in': 'title', 'lang': 'tr', 'max': 8, 'apikey': key},
                timeout=10,
            )
            if response.status_code != 200:
                print(f"❌ GNews hatası: {response.status_code} {response.text[:200]}")
                return None
            return [
                self._item(a.get('title'), a.get('description'), (a.get('source') or {}).get('name', 'GNews'),
                           a.get('publishedAt'), a.get('url'))
                for a in response.json().get('articles', [])[:6]
            ]
        except Exception as e:
            print(f"❌ GNews hatası: {e}")
            return None

    def _get_newsdata_news(self, query, key):
        """NewsData.io API"""
        try:
            response = requests.get(
                "https://newsdata.io/api/1/latest",
                params={'apikey': key, 'qInTitle': query, 'language': 'tr'},
                timeout=10,
            )
            if response.status_code != 200:
                print(f"❌ NewsData hatası: {response.status_code} {response.text[:200]}")
                return None
            return [
                self._item(a.get('title'), a.get('description'), a.get('source_id', 'NewsData'),
                           a.get('pubDate'), a.get('link'))
                for a in response.json().get('results', [])[:6]
            ]
        except Exception as e:
            print(f"❌ NewsData hatası: {e}")
            return None

    # --- Kripto haberleri --------------------------------------------------

    def get_crypto_news(self):
        """Kripto haberleri. CryptoCompare anahtarı varsa onu, yoksa finans
        haber kaynaklarını kripto araması ile kullanır. Bloklayan çağrı."""
        def fetch():
            if _is_configured(CRYPTOCOMPARE_API_KEY):
                news = self._get_cryptocompare_news()
                if news:
                    return news
            return self._fetch_financial('crypto')
        return self._cached('crypto', fetch) or []

    def _get_cryptocompare_news(self):
        """CryptoCompare API (anahtar gerekli)"""
        try:
            headers = {'authorization': f'Apikey {CRYPTOCOMPARE_API_KEY}'}
            response = requests.get(
                "https://min-api.cryptocompare.com/data/v2/news/",
                params={'lang': 'EN', 'categories': 'BTC,ETH,Blockchain', 'excludeCategories': 'Sponsored'},
                headers=headers,
                timeout=10,
            )
            if response.status_code != 200:
                print(f"❌ CryptoCompare hatası: {response.status_code}")
                return None
            data = response.json().get('Data')
            if not isinstance(data, list):
                print(f"❌ CryptoCompare yanıtı beklenmedik: {response.text[:200]}")
                return None
            return [
                self._item(a.get('title'), a.get('body'), (a.get('source_info') or {}).get('name') or a.get('source'),
                           a.get('published_on'), a.get('url'))
                for a in data[:5]
            ]
        except Exception as e:
            print(f"❌ CryptoCompare hatası: {e}")
            return None

    def configured_sources(self):
        """Tanımlı finans haber kaynaklarının adları"""
        names = [('NewsAPI', NEWSAPI_KEY), ('GNews', GNEWS_API_KEY), ('NewsData', NEWSDATA_API_KEY),
                 ('CryptoCompare', CRYPTOCOMPARE_API_KEY)]
        return [name for name, key in names if _is_configured(key)]

# Global instance
real_news_service = RealNewsService()
