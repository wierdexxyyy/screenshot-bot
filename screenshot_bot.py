import logging
import os
from io import BytesIO
from PIL import Image, ImageDraw, ImageFont
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

# ──────────────────────────────────────────────
# НАЛАШТУВАННЯ — заміни ці значення
# ──────────────────────────────────────────────
BOT_TOKEN = "8797131531:AAFxwaYPDA6zMHgguCDe_EiE8vA0zyZnRmc"   # токен від @BotFather
DESTINATION_CHAT_ID = "-1003821062018" # @назва_каналу або числовий ID чату
ALLOWED_USER_IDS = []                 # [] = всі користувачі, або [123456, 789012] для обмеження
# ──────────────────────────────────────────────

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# Стани розмови
WAITING_CAPTION = 1

# Тимчасове сховище фото {user_id: file_id}
user_photos: dict[int, str] = {}


def is_allowed(user_id: int) -> bool:
    if not ALLOWED_USER_IDS:
        return True
    return user_id in ALLOWED_USER_IDS


def add_caption_to_image(image_bytes: bytes, caption: str) -> BytesIO:
    """Накладає підпис на нижню частину зображення."""
    img = Image.open(BytesIO(image_bytes)).convert("RGBA")
    width, height = img.size

    # Висота панелі підпису (5% від висоти, мінімум 40px)
    bar_height = max(40, int(height * 0.07))
    font_size = max(16, bar_height - 12)

    # Спробуємо завантажити шрифт, інакше — дефолтний
    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", font_size)
    except Exception:
        try:
            font = ImageFont.truetype("/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf", font_size)
        except Exception:
            font = ImageFont.load_default()

    # Нове зображення з місцем для підпису
    new_height = height + bar_height
    new_img = Image.new("RGBA", (width, new_height), (0, 0, 0, 255))
    new_img.paste(img, (0, 0))

    draw = ImageDraw.Draw(new_img)

    # Фон підпису
    draw.rectangle([(0, height), (width, new_height)], fill=(20, 20, 20, 255))

    # Текст по центру
    try:
        bbox = draw.textbbox((0, 0), caption, font=font)
        text_w = bbox[2] - bbox[0]
        text_h = bbox[3] - bbox[1]
    except AttributeError:
        text_w, text_h = draw.textsize(caption, font=font)

    x = (width - text_w) // 2
    y = height + (bar_height - text_h) // 2

    # Тінь
    draw.text((x + 1, y + 1), caption, font=font, fill=(0, 0, 0, 180))
    # Основний текст
    draw.text((x, y), caption, font=font, fill=(255, 255, 255, 255))

    output = BytesIO()
    new_img.convert("RGB").save(output, format="JPEG", quality=95)
    output.seek(0)
    return output


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

    # Беремо найкращу якість фото
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
    processing_msg = await update.message.reply_text("⏳ Обробляю зображення...")

    try:
        # Завантажуємо фото
        file = await context.bot.get_file(file_id)
        image_bytes = await file.download_as_bytearray()

        # Накладаємо підпис
        result_image = add_caption_to_image(bytes(image_bytes), caption)

        # Відправляємо у канал
        sent = await context.bot.send_photo(
            chat_id=DESTINATION_CHAT_ID,
            photo=result_image,
            caption=f"📋 {caption}\n👤 від: @{update.effective_user.username or update.effective_user.first_name}",
        )

        await processing_msg.edit_text(
            f"✅ Готово! Скриншот з підписом «{caption}» відправлено у канал."
        )
    except Exception as e:
        logger.error(f"Помилка: {e}")
        await processing_msg.edit_text(f"❌ Помилка при відправці: {e}")

    return ConversationHandler.END


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    user_photos.pop(user_id, None)
    await query.edit_message_text("❌ Скасовано. Надішли нове фото коли будеш готовий.")
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
        fallbacks=[
            CommandHandler("cancel", cancel_command),
        ],
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(conv_handler)

    logger.info("Бот запущено...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
