import logging
import os
from telegram import Update, InputMediaPhoto, InlineKeyboardButton, InlineKeyboardMarkup
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
user_data: dict[int, list] = {}


def is_allowed(user_id: int) -> bool:
    if not ALLOWED_USER_IDS:
        return True
    return user_id in ALLOWED_USER_IDS


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_allowed(update.effective_user.id):
        await update.message.reply_text("⛔ Доступ заборонено.")
        return
    await update.message.reply_text(
        "👋 Привіт! Надішли 1-3 фото одночасно або по одному.\n"
        "Потім введи підпис — і все піде у канал."
    )


async def photos_received(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not is_allowed(update.effective_user.id):
        return ConversationHandler.END

    user_id = update.effective_user.id
    if user_id not in user_data:
        user_data[user_id] = []

    # Якщо надіслано альбом (media_group)
    if update.message.media_group_id:
        media_group_id = update.message.media_group_id
        if not context.user_data.get("media_group_id"):
            context.user_data["media_group_id"] = media_group_id

        if context.user_data.get("media_group_id") == media_group_id:
            user_data[user_id].append(update.message.photo[-1].file_id)
            if len(user_data[user_id]) > 3:
                user_data[user_id] = user_data[user_id][:3]

        # Чекаємо поки всі фото альбому прийдуть
        import asyncio
        await asyncio.sleep(1)

    else:
        user_data[user_id].append(update.message.photo[-1].file_id)
        if len(user_data[user_id]) > 3:
            user_data[user_id] = user_data[user_id][:3]

    count = len(user_data[user_id])
    keyboard = [[
        InlineKeyboardButton("✅ Готово", callback_data="done"),
        InlineKeyboardButton("❌ Скасувати", callback_data="cancel"),
    ]]
    await update.message.reply_text(
        f"📸 {count} фото отримано. Введи підпис або надішли ще (макс 3):",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )
    return WAITING_CAPTION


async def done_button(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id

    if not user_data.get(user_id):
        await query.edit_message_text("⚠️ Спочатку надішли фото.")
        return WAITING_CAPTION

    await query.edit_message_text("✏️ Введи підпис:")
    return WAITING_CAPTION


async def caption_received(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.effective_user.id
    caption = update.message.text.strip()

    if user_id not in user_data or not user_data[user_id]:
        await update.message.reply_text("⚠️ Спочатку надішли фото.")
        return ConversationHandler.END

    photos = user_data.pop(user_id)
    context.user_data.clear()
    processing_msg = await update.message.reply_text("⏳ Відправляю...")
    username = update.effective_user.username or update.effective_user.first_name
    full_caption = f"📧 {caption}\n👤 від: @{username}"

    try:
        if len(photos) == 1:
            await context.bot.send_photo(
                chat_id=DESTINATION_CHAT_ID,
                photo=photos[0],
                caption=full_caption,
            )
        else:
            media = [InputMediaPhoto(media=p) for p in photos]
            media[-1] = InputMediaPhoto(media=photos[-1], caption=full_caption)
            await context.bot.send_media_group(
                chat_id=DESTINATION_CHAT_ID,
                media=media,
            )
        await processing_msg.edit_text("✅ Готово! Відправлено у канал.")
    except Exception as e:
        logger.error(f"Помилка: {e}")
        await processing_msg.edit_text(f"❌ Помилка: {e}")

    return ConversationHandler.END


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    user_data.pop(query.from_user.id, None)
    context.user_data.clear()
    await query.edit_message_text("❌ Скасовано.")
    return ConversationHandler.END


async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_data.pop(update.effective_user.id, None)
    context.user_data.clear()
    await update.message.reply_text("❌ Скасовано.")
    return ConversationHandler.END


def main() -> None:
    app = Application.builder().token(BOT_TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[MessageHandler(filters.PHOTO, photos_received)],
        states={
            WAITING_CAPTION: [
                MessageHandler(filters.PHOTO, photos_received),
                MessageHandler(filters.TEXT & ~filters.COMMAND, caption_received),
                CallbackQueryHandler(done_button, pattern="^done$"),
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
