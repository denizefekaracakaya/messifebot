# Media handling functions

from telegram import Update
from telegram.ext import CallbackContext


def handle_media(update: Update, context: CallbackContext) -> None:
    update.message.reply_text('Media received.')
