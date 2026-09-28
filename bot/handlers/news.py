# bot/handlers/news.py
import asyncio
from datetime import datetime
from telegram import Update
from telegram.ext import ContextTypes, CommandHandler
from bot.services.real_news_service import real_news_service
from bot.services.crypto_service import crypto_service
from bot.services.market_service import get_market_summary
from bot.utils.helpers import esc, edit_long, format_quote

NO_NEWS_TEXT = (
    "📭 Şu anda haber alınamadı.\n\n"
    "Haber kaynağı yanıt vermedi veya .env dosyasında haber API anahtarı "
    "(NEWSAPI_KEY / GNEWS_API_KEY / NEWSDATA_API_KEY) tanımlı değil."
)


def format_news(header: str, news_items: list, bullet: str = "📰", footer: str = "") -> str:
    """Haber listesini HTML mesajına çevir"""
    message = f"{header}\n\n"
    message += f"⏰ Son Güncelleme: {datetime.now().strftime('%d.%m.%Y %H:%M')}\n\n"

    for i, news in enumerate(news_items, 1):
        emoji = bullet or ("🔴" if news.get('importance') == 'high' else "🟡")
        title = esc(news['title'])
        if news.get('url'):
            title = f'<a href="{esc(news["url"])}">{title}</a>'
        message += f"{emoji} <b>{title}</b>\n"
        if news.get('description'):
            message += f"📝 {esc(news['description'])}\n"
        message += f"🗞 {esc(news['source'])} | 🕐 {esc(news['published_at'])}\n"

        if i < len(news_items):
            message += "─" * 30 + "\n\n"

    if footer:
        message += f"\n{footer}"
    return message


async def _send_news(update: Update, loading_text: str, fetch, header: str, bullet: str, footer: str = ""):
    loading_msg = await update.message.reply_text(loading_text)
    try:
        news_items = await asyncio.to_thread(fetch)
        if not news_items:
            await loading_msg.edit_text(NO_NEWS_TEXT)
            return
        await edit_long(loading_msg, format_news(header, news_items, bullet, footer))
    except Exception as e:
        print(f"❌ Haber komutu hatası: {e}")
        await loading_msg.edit_text("❌ Haberler alınırken bir hata oluştu.")


async def news_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Borsa / piyasa haberleri"""
    await _send_news(
        update, "📈 Borsa haberleri getiriliyor...",
        lambda: real_news_service.get_financial_news('markets'),
        "📊 <b>BORSA &amp; PİYASA HABERLERİ</b>", bullet=None,
    )


async def economy_news_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Ekonomi haberleri"""
    await _send_news(
        update, "💼 Ekonomi haberleri getiriliyor...",
        lambda: real_news_service.get_financial_news('economy'),
        "💼 <b>EKONOMİ HABERLERİ</b>", bullet="📰",
    )


async def crypto_news_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Kripto haberleri"""
    await _send_news(
        update, "🪙 Kripto para haberleri getiriliyor...",
        real_news_service.get_crypto_news,
        "💰 <b>KRİPTO PARA HABERLERİ</b>", bullet="🚀",
        footer="💡 Not: Kripto yatırımları yüksek risk içerir.",
    )


async def crypto_top_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """En popüler 10 kriptoyu göster"""
    loading_msg = await update.message.reply_text("💰 En popüler kripto paralar getiriliyor...")
    try:
        crypto_data = await asyncio.to_thread(crypto_service.get_top_cryptos, 10)
        await edit_long(loading_msg, crypto_service.format_crypto_message(crypto_data))
    except Exception as e:
        print(f"❌ Crypto top komutu hatası: {e}")
        await loading_msg.edit_text("❌ Kripto verileri alınamadı.")


async def market_summary_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Piyasa özeti"""
    loading_msg = await update.message.reply_text("📊 Piyasa verileri getiriliyor...")
    try:
        summary = await asyncio.to_thread(get_market_summary)

        sections = [
            ('bist', "🏦 <b>Borsa İstanbul</b>"),
            ('fx', "💵 <b>Döviz</b>"),
            ('commodity', "🥇 <b>Emtia</b>"),
            ('crypto', "🪙 <b>Kripto</b>"),
        ]
        message = "📊 <b>PİYASA ÖZETİ</b>\n\n"
        for key, title in sections:
            message += f"{title}\n"
            for name, unit, quote in summary.get(key, []):
                message += format_quote(name, unit, quote)
            message += "\n"

        message += "ℹ️ Değişimler bir önceki kapanışa / son 24 saate göredir. Veriler gecikmeli olabilir.\n"
        message += "🔎 Kaynak: Yahoo Finance, CoinGecko\n"
        message += f"⏰ {datetime.now().strftime('%d.%m.%Y %H:%M')}"

        await edit_long(loading_msg, message)

    except Exception as e:
        print(f"❌ Piyasa özeti hatası: {e}")
        await loading_msg.edit_text("❌ Piyasa özeti alınırken bir hata oluştu.")


def setup_news_handlers(application):
    """Haber handler'larını kur"""
    application.add_handler(CommandHandler("news", news_command))
    application.add_handler(CommandHandler("economy", economy_news_command))
    application.add_handler(CommandHandler("crypto", crypto_top_command))
    application.add_handler(CommandHandler("cryptonews", crypto_news_command))
    application.add_handler(CommandHandler("market", market_summary_command))
    print("✅ Haber handler'ları kuruldu")
