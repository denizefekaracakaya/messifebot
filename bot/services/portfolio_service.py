# bot/services/portfolio_service.py
from bot.database import db
from bot.services.crypto_service import crypto_service
from bot.services.assets import asset_resolver


def _ensure_provider_id(item: dict, user_id: int) -> dict:
    """Eski, sadece sembolle kaydedilmiş kalemleri kesin varlık ID'sine bağlar.
    Belirsiz veya bulunamayan semboller olduğu gibi bırakılır (fiyatsız gösterilir)."""
    if item.get('provider_id'):
        return item
    resolution = asset_resolver.resolve(item['coin_symbol'], user_id)
    if resolution.ok:
        asset = resolution.asset
        db.set_portfolio_asset(item['id'], asset.provider_id, asset.symbol or item['coin_symbol'], asset.name)
        item = dict(item, provider_id=asset.provider_id, asset_name=asset.name,
                    coin_symbol=asset.symbol or item['coin_symbol'])
    return item


def value_portfolio(user_id: int) -> dict:
    """Portföyü güncel fiyatlarla değerler (bloklayan çağrı - to_thread ile kullanın).

    Dönüş: {'items': [...], 'total_investment', 'total_current', 'total_profit', 'missing_prices'}
    Fiyatı alınamayan varlıklar toplam değere katılmaz ve 'missing_prices' içinde listelenir.
    """
    portfolio = [_ensure_provider_id(item, user_id) for item in db.get_user_portfolio(user_id)]
    prices = crypto_service.get_prices_by_ids(item['provider_id'] for item in portfolio)

    items = []
    total_investment = total_current = priced_investment = 0.0
    missing = []

    for item in portfolio:
        symbol = item['coin_symbol'].upper()
        amount = item['amount']
        investment = amount * item['buy_price']
        total_investment += investment

        current_price = prices.get(item['provider_id']) if item['provider_id'] else None
        entry = {
            'id': item['id'],
            'symbol': symbol,
            'name': item.get('asset_name') or symbol,
            'provider_id': item['provider_id'],
            'amount': amount,
            'buy_price': item['buy_price'],
            'investment': investment,
            'current_price': current_price,
            'current_value': None,
            'profit': None,
            'profit_pct': None,
        }

        if current_price is None:
            missing.append(symbol)
        else:
            value = amount * current_price
            entry['current_value'] = value
            entry['profit'] = value - investment
            entry['profit_pct'] = (value - investment) / investment * 100 if investment > 0 else 0.0
            total_current += value
            priced_investment += investment

        items.append(entry)

    return {
        'items': items,
        'total_investment': total_investment,
        'total_current': total_current,
        # Kar/zarar sadece fiyatı bilinen varlıklar üzerinden hesaplanır
        'total_profit': total_current - priced_investment,
        'missing_prices': missing,
    }
