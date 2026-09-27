from .messages import setup_messages
from .commands import setup_commands
from .stats import setup_stats_handlers
from .fun import setup_fun_handlers
from .admin import setup_admin_handlers
from .news import setup_news_handlers
from .portfolio import setup_portfolio_handlers
from .reporting import setup_reporting_handlers
from .alerts import setup_alert_handlers
from .assets import setup_asset_handlers

def setup_handlers(application):
    setup_messages(application)  # istatistik (group -1) + sohbet yanıtı (group 1)
    setup_commands(application)
    setup_stats_handlers(application)
    setup_fun_handlers(application)
    setup_admin_handlers(application)
    setup_news_handlers(application)
    setup_portfolio_handlers(application)
    setup_reporting_handlers(application)
    setup_alert_handlers(application)
    setup_asset_handlers(application)
    print("✅ Tüm handler'lar kuruldu")
