# bot/services/conversation_actions.py
"""Sohbet katmanının kullanabileceği SINIRLI, salt-okunur araçlar.

ConversationEngine veritabanına veya servislere doğrudan erişmez; sadece bu sınıftaki
metotları çağırır. Tüm metotlar bloklayan çağrılardır (engine bunları to_thread ile çalıştırır).
Veri değiştiren işlemler (alarm kurma vb.) burada YOKTUR: onlar kullanıcı onayından sonra
ilgili handler tarafından mevcut komut altyapısıyla yapılır.
"""
from typing import Optional


class ConversationActions:
    def __init__(self, resolver=None, crypto=None, db=None, news=None, market_summary=None, value_portfolio=None):
        # Varsayılanlar uygulamanın gerçek servisleridir; testlerde sahteleri verilebilir
        if resolver is None:
            from bot.services.assets import asset_resolver as resolver
        if crypto is None:
            from bot.services.crypto_service import crypto_service as crypto
        if db is None:
            from bot.database import db
        if news is None:
            from bot.services.real_news_service import real_news_service as news
        if market_summary is None:
            from bot.services.market_service import get_market_summary as market_summary
        if value_portfolio is None:
            from bot.services.portfolio_service import value_portfolio
        self._resolver = resolver
        self._crypto = crypto
        self._db = db
        self._news = news
        self._market_summary = market_summary
        self._value_portfolio = value_portfolio

    def resolve_asset(self, query: str, user_id: int, offline: bool = False):
        return self._resolver.resolve(query, user_id, offline=offline)

    def get_snapshot(self, provider_id: str) -> Optional[dict]:
        """None: veri kaynağına ulaşılamadı, {}: bu varlığın piyasa verisi yok"""
        return self._crypto.get_market_snapshot(provider_id)

    def get_portfolio(self, user_id: int) -> dict:
        return self._value_portfolio(user_id)

    def get_portfolio_value_before(self, user_id: int, hours: int = 20):
        return self._db.get_value_before(user_id, hours=hours)

    def get_alerts(self, user_id: int) -> list:
        return self._db.get_user_alerts(user_id)

    def get_news(self, topic: str) -> list:
        if topic == 'crypto':
            return self._news.get_crypto_news()
        return self._news.get_financial_news('economy' if topic == 'economy' else 'markets')

    def get_market(self) -> dict:
        return self._market_summary()
