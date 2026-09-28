# bot/services/crypto_service.py
import threading
import time
import requests
from datetime import datetime
from bot.utils.helpers import esc
from bot.services.asset_provider import CoinGeckoProvider, ProviderError

CACHE_SECONDS = 60  # CoinGecko ücretsiz API dakikada az sayıda isteğe izin veriyor


class CryptoService:
    def __init__(self):
        self.base_url = "https://api.coingecko.com/api/v3"
        self.provider = CoinGeckoProvider(self.base_url)
        self._lock = threading.Lock()
        self._price_cache = {}  # SYMBOL -> (zaman, fiyat veya None)
        self._top_cache = None  # (zaman, liste)
        self._snapshot_cache = {}  # provider_id -> (zaman, snapshot)

    def _get(self, url, params):
        """GET isteği; 429 (rate limit) alınırsa bir kez kısa bekleyip tekrar dener"""
        response = requests.get(url, params=params, timeout=10)
        if response.status_code == 429:
            time.sleep(3)
            response = requests.get(url, params=params, timeout=10)
        return response
    
    def get_top_cryptos(self, limit=10):
        """En popüler kripto paraları getir (en fazla 10, 60 sn cache). Hata durumunda None."""
        with self._lock:
            if self._top_cache and time.time() - self._top_cache[0] < CACHE_SECONDS:
                return self._top_cache[1][:limit]
        try:
            params = {
                'vs_currency': 'usd',
                'order': 'market_cap_desc',
                'per_page': max(limit, 10),
                'page': 1,
                'sparkline': False,
                'price_change_percentage': '1h,24h,7d'
            }
            
            response = self._get(f"{self.base_url}/coins/markets", params)
            
            if response.status_code == 200:
                data = response.json()
                with self._lock:
                    self._top_cache = (time.time(), data)
                return data[:limit]
            else:
                print(f"❌ Crypto API hatası: {response.status_code}")
                return None
                
        except Exception as e:
            print(f"❌ Crypto servis hatası: {e}")
            return None
    
    def get_prices_by_ids(self, provider_ids):
        """Kesin sağlayıcı ID'lerinin USD fiyatları: {'pi-network': 0.09, 'olmayan-id': None}.
        Fiyatı alınamayan ID'ler None döner (0 değil). Sonuçlar 60 sn cache'lenir."""
        ids = sorted({i for i in provider_ids if i})
        if not ids:
            return {}

        now = time.time()
        prices = {}
        with self._lock:
            for coin_id in ids:
                cached = self._price_cache.get(coin_id)
                if cached and now - cached[0] < CACHE_SECONDS:
                    prices[coin_id] = cached[1]
        missing = [i for i in ids if i not in prices]
        if not missing:
            return prices

        for coin_id in missing:
            prices[coin_id] = None
        try:
            fetched = self.provider.prices(missing)
        except ProviderError as e:
            # Hata durumunu cache'leme, bir sonraki çağrıda tekrar denensin
            print(f"❌ Fiyat alma hatası: {e}")
            return prices

        with self._lock:
            for coin_id in missing:
                prices[coin_id] = fetched.get(coin_id)
                self._price_cache[coin_id] = (now, prices[coin_id])
        return prices

    def get_price(self, provider_id):
        return self.get_prices_by_ids([provider_id]).get(provider_id)

    def get_market_snapshot(self, provider_id):
        """Tek varlık için fiyat + 24s değişim: {'price','change_24h','high_24h','low_24h','market_cap_rank'}.
        Veri alınamazsa None; varlığın piyasa verisi yoksa {} döner. 60 sn cache'lenir."""
        now = time.time()
        with self._lock:
            cached = self._snapshot_cache.get(provider_id)
            if cached and now - cached[0] < CACHE_SECONDS:
                return cached[1]
        try:
            coin = self.provider.market_data([provider_id]).get(provider_id)
        except ProviderError as e:
            print(f"❌ Piyasa verisi alma hatası: {e}")
            return None
        snapshot = {}
        if coin and coin.get('current_price') is not None:
            snapshot = {
                'price': float(coin['current_price']),
                'change_24h': coin.get('price_change_percentage_24h'),
                'high_24h': coin.get('high_24h'),
                'low_24h': coin.get('low_24h'),
                'market_cap_rank': coin.get('market_cap_rank'),
            }
        with self._lock:
            self._snapshot_cache[provider_id] = (now, snapshot)
            if snapshot:
                self._price_cache[provider_id] = (now, snapshot['price'])
        return snapshot

    def format_crypto_message(self, crypto_data):
        """Kripto verilerini formatla (HTML)"""
        if not crypto_data:
            return "❌ Kripto verileri şu anda alınamadı, lütfen biraz sonra tekrar deneyin."
        
        message = "💰 <b>EN POPÜLER 10 KRİPTO PARA</b>\n\n"
        
        for i, crypto in enumerate(crypto_data[:10], 1):
            # Emojiler
            if i == 1: emoji = "🥇"
            elif i == 2: emoji = "🥈" 
            elif i == 3: emoji = "🥉"
            else: emoji = "🔸"
            
            # Fiyat değişimi
            change_24h = crypto.get('price_change_percentage_24h') or 0
            change_emoji = "📈" if change_24h > 0 else "📉" if change_24h < 0 else "➡️"
            
            message += f"{emoji} <b>{esc(crypto['name'])} ({esc(crypto['symbol'].upper())})</b>\n"
            message += f"💵 Fiyat: ${crypto['current_price'] or 0:,.2f}\n"
            message += f"{change_emoji} 24s: {change_24h:+.2f}%\n"
            message += f"🏦 Piyasa Değeri: ${crypto['market_cap'] or 0:,.0f}\n"
            
            if i < len(crypto_data[:10]):
                message += "─" * 30 + "\n\n"
        
        message += f"\n⏰ Son Güncelleme: {datetime.now().strftime('%d.%m.%Y %H:%M')}"
        return message

# Global instance
crypto_service = CryptoService()
