# bot/services/asset_provider.py
"""Kripto varlık sağlayıcısı (CoinGecko).

Varlıklar her zaman sağlayıcının kesin ID'si (ör. 'pi-network') ile tanımlanır.
Semboller (ör. 'PI') benzersiz değildir; sembolden ID'ye çözümleme AssetResolver'ın işidir.
"""
import time
import requests


class ProviderError(Exception):
    """Sağlayıcıya ulaşılamadı veya beklenmeyen yanıt döndü"""


class CoinGeckoProvider:
    name = "CoinGecko"

    def __init__(self, base_url: str = "https://api.coingecko.com/api/v3", timeout: int = 15):
        self.base_url = base_url
        self.timeout = timeout

    def _get(self, path: str, params: dict = None):
        """GET isteği; 429 (rate limit) alınırsa bir kez kısa bekleyip tekrar dener"""
        url = f"{self.base_url}{path}"
        try:
            for wait in (3, 8, None):
                response = requests.get(url, params=params, timeout=self.timeout)
                if response.status_code != 429 or wait is None:
                    break
                retry_after = response.headers.get("Retry-After", "")
                time.sleep(min(int(retry_after), 30) if retry_after.isdigit() else wait)
        except requests.RequestException as e:
            raise ProviderError(f"{path}: {e}") from e
        if response.status_code != 200:
            raise ProviderError(f"{path}: HTTP {response.status_code}")
        try:
            return response.json()
        except ValueError as e:
            raise ProviderError(f"{path}: geçersiz JSON") from e

    def list_assets(self) -> list:
        """Sağlayıcıdaki tüm varlıklar: [{'provider_id','symbol','name'}] (~20 bin kayıt, tek istek)"""
        data = self._get("/coins/list")
        return [
            {'provider_id': c['id'], 'symbol': c.get('symbol') or '', 'name': c.get('name') or ''}
            for c in data if c.get('id')
        ]

    def search(self, query: str) -> list:
        """Serbest metin arama (isim/sembol, bulanık). Sonuçlar piyasa değeri sırasına göre gelir."""
        data = self._get("/search", {'query': query})
        return [
            {
                'provider_id': c['id'],
                'symbol': c.get('symbol') or '',
                'name': c.get('name') or '',
                'market_cap_rank': c.get('market_cap_rank'),
            }
            for c in data.get('coins', []) if c.get('id')
        ]

    def top_ranks(self, pages: int = 4) -> dict:
        """Piyasa değerine göre ilk pages*250 varlığın sıralaması: {id: rank}"""
        ranks = {}
        for page in range(1, pages + 1):
            data = self._get("/coins/markets", {
                'vs_currency': 'usd', 'order': 'market_cap_desc',
                'per_page': 250, 'page': page, 'sparkline': 'false',
            })
            for coin in data:
                if coin.get('market_cap_rank'):
                    ranks[coin['id']] = coin['market_cap_rank']
        return ranks

    def market_data(self, provider_ids: list) -> dict:
        """ID'ler için sıralama ve fiyat: {id: {'market_cap_rank', 'current_price', ...}}.
        Piyasa verisi olmayan (işlem görmeyen) varlıklar sonuçta yer almaz."""
        ids = [i for i in dict.fromkeys(provider_ids) if i]
        result = {}
        for start in range(0, len(ids), 100):
            chunk = ids[start:start + 100]
            data = self._get("/coins/markets", {
                'vs_currency': 'usd',
                'ids': ','.join(chunk),
                'per_page': len(chunk),
                'page': 1,
                'sparkline': 'false',
            })
            for coin in data:
                result[coin['id']] = coin
        return result

    def prices(self, provider_ids: list) -> dict:
        """ID'lerin USD fiyatları: {id: fiyat}. Fiyatı olmayan ID'ler sonuçta yer almaz."""
        ids = [i for i in dict.fromkeys(provider_ids) if i]
        result = {}
        for start in range(0, len(ids), 200):
            chunk = ids[start:start + 200]
            data = self._get("/simple/price", {'ids': ','.join(chunk), 'vs_currencies': 'usd'})
            for coin_id, values in data.items():
                if isinstance(values, dict) and values.get('usd') is not None:
                    result[coin_id] = float(values['usd'])
        return result
