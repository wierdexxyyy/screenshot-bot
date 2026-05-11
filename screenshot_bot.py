import logging
import os
from io import BytesIO
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ConversationHandler,
    filters,
    ContextTypes,
)

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
DESTINATION_CHAT_ID = os.getenv("DESTINATION_CHAT_ID", "")
ALLOWED_USER_IDS = []

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

WAITING_CAPTION = 1
user_photos: dict[int, str] = {}


def is_allowed(user_id: int) -> bool:
    if not ALLOWED_USER_IDS:
        return True
    return user_id in ALLOWED_USER_IDS


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_allowed(update.effective_user.id):
        await update.message.reply_text("⛔ Доступ заборонено.")
        return
    await update.message.reply_text(
        "👋 Привіт! Надішли мені скриншот — я додам підпис і перешлю у канал.\n\n"
        "📸 Просто відправ фото зараз."
    )


async def photo_received(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not is_allowed(update.effective_user.id):
        return ConversationHandler.END

    photo = update.message.photo[-1]
    user_photos[update.effective_user.id] = photo.file_id

    keyboard = [[InlineKeyboardButton("❌ Скасувати", callback_data="cancel")]]
    await update.message.reply_text(
        "✅ Фото отримано!\n\n✏️ Тепер введи підпис для скриншоту:",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )
    return WAITING_CAPTION


async def caption_received(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.effective_user.id
    caption = update.message.text.strip()

    if user_id not in user_photos:
        await update.message.reply_text("⚠️ Спочатку надішли фото.")
        return ConversationHandler.END

    file_id = user_photos.pop(user_id)
    processing_msg = await update.message.reply_text("⏳ Відправляю...")

    try:
        await context.bot.send_photo(
            chat_id=DESTINATION_CHAT_ID,
            photo=file_id,
            caption=caption,
        )
        await processing_msg.edit_text(
            f"✅ Готово! Відправлено у канал з підписом «{caption}»."
        )
    except Exception as e:
        logger.error(f"Помилка: {e}")
        await processing_msg.edit_text(f"❌ Помилка: {e}")

    return ConversationHandler.END


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    user_photos.pop(query.from_user.id, None)
    await query.edit_message_text("❌ Скасовано.")
    return ConversationHandler.END


async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_photos.pop(update.effective_user.id, None)
    await update.message.reply_text("❌ Скасовано.")
    return ConversationHandler.END


def main() -> None:
    app = Application.builder().token(BOT_TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[MessageHandler(filters.PHOTO, photo_received)],
        states={
            WAITING_CAPTION: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, caption_received),
                CallbackQueryHandler(cancel, pattern="^cancel$"),
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel_command)],
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(conv_handler)

    logger.info("Бот запущено...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
