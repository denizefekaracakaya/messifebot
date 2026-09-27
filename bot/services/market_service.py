# bot/services/market_service.py
import requests

from bot.services.crypto_service import crypto_service

# (Yahoo Finance sembolü, görünen ad, birim)
MARKET_SYMBOLS = {
    'bist': [('XU100.IS', 'BIST 100', ''), ('XU030.IS', 'BIST 30', '')],
    'fx': [('USDTRY=X', 'USD/TRY', '₺'), ('EURTRY=X', 'EUR/TRY', '₺')],
    'commodity': [('GC=F', 'Altın (ONS)', '$'), ('BZ=F', 'Petrol (Brent)', '$')],
}

YAHOO_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
HEADERS = {'User-Agent': 'Mozilla/5.0 (compatible; messifebot/1.0)'}


def _yahoo_quote(symbol):
    """Yahoo Finance'ten son fiyat ve günlük değişim. Hata durumunda None."""
    try:
        response = requests.get(
            YAHOO_URL.format(symbol=symbol),
            params={'range': '1d', 'interval': '1d'},
            headers=HEADERS,
            timeout=10,
        )
        if response.status_code != 200:
            print(f"❌ Yahoo hatası ({symbol}): {response.status_code}")
            return None
        meta = response.json()['chart']['result'][0]['meta']
        price = meta.get('regularMarketPrice')
        prev = meta.get('chartPreviousClose') or meta.get('previousClose')
        if price is None:
            return None
        change = (price - prev) / prev * 100 if prev else None
        return {'price': float(price), 'change_pct': change}
    except Exception as e:
        print(f"❌ Yahoo hatası ({symbol}): {e}")
        return None


def get_market_summary():
    """Piyasa özeti verilerini getir (bloklayan çağrı - to_thread ile kullanın).

    Dönüş: {bölüm: [(ad, birim, quote veya None), ...]}
    """
    summary = {}
    for section, symbols in MARKET_SYMBOLS.items():
        summary[section] = [(name, unit, _yahoo_quote(symbol)) for symbol, name, unit in symbols]

    top = crypto_service.get_top_cryptos(2) or []
    crypto_rows = []
    for coin in top:
        crypto_rows.append((coin['name'], '$', {
            'price': coin.get('current_price'),
            'change_pct': coin.get('price_change_percentage_24h'),
        }))
    summary['crypto'] = crypto_rows or [('Bitcoin', '$', None), ('Ethereum', '$', None)]
    return summary
