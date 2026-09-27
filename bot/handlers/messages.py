# bot/handlers/messages.py
"""Serbest metin mesajları: istatistik kaydı + sohbet.

Handler öncelikleri (python-telegram-bot grupları):
    group -1 : record_message_stats  — her metin mesajı sayılır, hiçbir zaman yanıt vermez
    group  0 : komutlar, buton callback'leri, portföy "EKLE ..." — kendi işini yapar
               (EKLE handler'ı ApplicationHandlerStop ile sohbete geçişi keser)
    group  1 : handle_text_message — sadece yukarıdakilerin almadığı mesajlar için sohbet
Komutlar (/…) filters.COMMAND ile sohbetten tamamen hariçtir.

Sohbet mantığının kendisi bot/services/conversation_engine.py içindedir; burası sadece
Telegram'a özgü işleri yapar: kime yanıt verileceği, spam koruması, gönderme ve butonlar.
"""
import logging
import re
import time

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import ContextTypes, MessageHandler, CallbackQueryHandler, filters

from bot.database import db
from bot.services.anti_spam import AntiSpam
from bot.services.conversation_actions import ConversationActions
from bot.services.conversation_engine import ConversationEngine
from bot.services.text_normalizer import normalize
from bot.handlers.asset_picker import send_picker
from bot.utils.helpers import reply_long

logger = logging.getLogger(__name__)

CONFIRM_TTL_SECONDS = 300
MAX_PENDING_CONFIRMS = 10

conversation_engine = ConversationEngine(ConversationActions())
anti_spam = AntiSpam()


async def record_message_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Tüm metin mesajlarının istatistiklerini kaydet (yanıt vermez)"""
    try:
        message = update.message
        if not message or not message.from_user or message.from_user.is_bot:
            return

        user = message.from_user
        chat = message.chat
        is_group = chat.type in ['group', 'supergroup']

        db.add_message(
            user_id=user.id,
            username=user.username or "",
            first_name=user.first_name or "",
            last_name=user.last_name or "",
            group_id=chat.id if is_group else None,
            group_title=chat.title if is_group else None
        )
    except Exception as e:
        print(f"❌ İstatistik kaydetme hatası: {e}")


def is_addressed_to_bot(message, bot_username: str, bot_id: int) -> bool:
    """Grupta mesaj bota mı yazıldı? (mention veya bota yanıt)"""
    replied = message.reply_to_message
    if replied and replied.from_user and replied.from_user.id == bot_id:
        return True
    text = (message.text or "").lower()
    return bool(bot_username) and f"@{bot_username.lower()}" in text


def strip_bot_mention(text: str, bot_username: str) -> str:
    if not bot_username:
        return text
    return re.sub(f"@{re.escape(bot_username)}", "", text, flags=re.IGNORECASE).strip()


async def handle_text_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Sohbet: özel sohbette her mesaja, grupta sadece bota yazılanlara yanıt verir"""
    message = update.message
    if not message or not message.text or not message.from_user or message.from_user.is_bot:
        return  # botlar (kendimiz dahil) hiçbir zaman işlenmez

    is_private = message.chat.type == 'private'
    if not is_private and not is_addressed_to_bot(message, context.bot.username, context.bot.id):
        return

    text = strip_bot_mention(message.text, context.bot.username)
    if not text:
        return

    allowed, reason = anti_spam.allow(message.chat.id, message.from_user.id, normalize(text), not is_private)
    if not allowed:
        logger.info("conversation throttled reason=%s", reason)
        return

    try:
        reply = await conversation_engine.handle(
            text, chat_id=message.chat.id, user_id=message.from_user.id,
            user_name=message.from_user.first_name or "",
        )
        if reply.kind == "pick":
            await send_picker(message, context, reply.query, reply.candidates, 'chat', reply.payload,
                              header=reply.text)
        elif reply.kind == "confirm":
            await _send_confirmation(message, context, reply)
        elif reply.text:
            await reply_long(message, reply.text)
    except Exception:
        logger.exception("conversation send failed")
        try:
            await message.reply_text("Bir şeyler ters gitti, lütfen biraz sonra tekrar dene.")
        except Exception:
            pass


# ------------------------------------------------------------------ onay akışı

async def _send_confirmation(message, context, reply):
    """Veri değiştiren bir işlem için (ör. alarm kurma) onay butonları göster"""
    pending = context.user_data.setdefault('chat_confirms', {})
    seq = context.user_data.get('chat_confirm_seq', 0) + 1
    context.user_data['chat_confirm_seq'] = seq
    token = str(seq)
    pending[token] = dict(reply.payload, created=time.time())
    for old in sorted(pending, key=int)[:-MAX_PENDING_CONFIRMS]:
        pending.pop(old, None)

    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Onayla", callback_data=f"chat:ok:{token}"),
        InlineKeyboardButton("✖️ İptal", callback_data=f"chat:no:{token}"),
    ]])
    await message.reply_text(reply.text, parse_mode=ParseMode.HTML, reply_markup=keyboard)


async def confirm_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """'chat:ok:<token>' / 'chat:no:<token>' — sadece onayı isteyen kullanıcının user_data'sında bulunur"""
    query = update.callback_query
    await query.answer()
    try:
        _, decision, token = query.data.split(":", 2)
    except ValueError:
        return

    pending = context.user_data.get('chat_confirms', {}).pop(token, None)
    if pending is None or time.time() - pending['created'] > CONFIRM_TTL_SECONDS:
        await query.edit_message_text("⌛ Bu onayın süresi doldu. İstersen tekrar yazabilirsin.")
        return
    if decision != "ok":
        await query.edit_message_text("✖️ Tamam, iptal ettim.")
        return

    if pending.get('action') == 'create_alert':
        from bot.handlers.alerts import create_price_alert  # mevcut alarm altyapısını kullan
        text = await create_price_alert(query.from_user.id, pending['asset'], pending['alert_type'], pending['target'])
        await query.edit_message_text(text, parse_mode=ParseMode.HTML)


async def cleanup_contexts_job(context: ContextTypes.DEFAULT_TYPE):
    removed = conversation_engine.contexts.cleanup()
    if removed:
        logger.info("conversation contexts expired=%d active=%d", removed, len(conversation_engine.contexts))


def setup_messages(application):
    """Sohbet handler'larını kur (öncelik sırası için modül açıklamasına bakın)"""
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, record_message_stats), group=-1)
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_message), group=1)
    application.add_handler(CallbackQueryHandler(confirm_callback_handler, pattern=r"^chat:(ok|no):"))
    application.job_queue.run_repeating(cleanup_contexts_job, interval=600, first=600, name="conversation_cleanup")
    print("✅ Sohbet handler'ları kuruldu")
