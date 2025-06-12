import logging
import base64
from io import BytesIO
import requests
import os
from dotenv import load_dotenv
import asyncio
import telegram

from deep_translator import GoogleTranslator
from telegram import Update, Bot, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
    ConversationHandler,
)

# Загружаем переменные окружения
load_dotenv()

logger = logging.getLogger("ImageGenBot")
logger.setLevel(logging.INFO)
logger.addHandler(logging.StreamHandler())

CONFIG = {
    "TELEGRAM_TOKEN": os.getenv("TELEGRAM_TOKEN"),
    "STABILITY_API_KEY": os.getenv("STABILITY_API_KEY"),
    "HF_TOKEN": os.getenv("HF_TOKEN")
}

MODEL_CHOICE, PROMPT_INPUT = range(2)

bot = Bot(token=CONFIG["TELEGRAM_TOKEN"])

def generate_stability_image(prompt: str) -> BytesIO | None:
    """Генерация через Stability AI."""
    try:
        response = requests.post(
            "https://api.stability.ai/v2beta/stable-image/generate/sd3",
            headers={"Authorization": f"Bearer {CONFIG['STABILITY_API_KEY']}"},
            files={"none": ''},
            data={
                "prompt": prompt,
                "output_format": "jpeg",
                "width": 1024,
                "height": 1024,
                "seed": 0,
                "cfg_scale": 7
            },
            timeout=40
        )
        return BytesIO(response.content) if response.ok else None
    except Exception as e:
        logger.error(f"Stability AI error: {e}")
        return None

def generate_hf_image(prompt: str) -> BytesIO | None:
    """Генерация через Hugging Face."""
    try:
        response = requests.post(
            "https://router.huggingface.co/nebius/v1/images/generations",
            headers={"Authorization": f"Bearer {CONFIG['HF_TOKEN']}"},
            json={
                "model": "black-forest-labs/flux-dev",
                "prompt": prompt,
                "response_format": "b64_json",
                "width": 1024,
                "height": 1024
            },
            timeout=40
        )
        if not response.ok:
            return None
        img_data = response.json()["data"][0]["b64_json"]
        return BytesIO(base64.b64decode(img_data))
    except Exception as e:
        logger.error(f"Hugging Face error: {e}")
        return None

def translate_prompt(text: str) -> str:
    """Перевод промпта с русского на английский."""
    try:
        return GoogleTranslator(source='ru', target='en').translate(text)
    except Exception as e:
        logger.warning(f"Translation failed: {e}")
        return text 

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Команда /start — выбор модели."""
    buttons = [
        [KeyboardButton("Stability AI")],
        [KeyboardButton("Hugging Face")]
    ]
    await update.message.reply_text(
        "Привет! Отправь описание изображения, и я его сгенерирую.\nВыбери модель:",
        reply_markup=ReplyKeyboardMarkup(buttons, resize_keyboard=True)
    )
    return MODEL_CHOICE

async def handle_model_choice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обработка выбора модели."""
    model = "stability" if "Stability" in update.message.text else "huggingface"
    context.user_data["model"] = model
    await update.message.reply_text(
        f"Выбрана модель: {update.message.text}\nТеперь отправь описание изображения:"
    )
    return PROMPT_INPUT

async def process_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Генерация изображения по промпту."""
    prompt = update.message.text.strip()
    if not prompt:
        await update.message.reply_text("Описание не может быть пустым!")
        return PROMPT_INPUT

    model = context.user_data.get("model", "stability")
    translated_prompt = translate_prompt(prompt)
    status_msg = await update.message.reply_text("Генерация...")

    image = (
        generate_stability_image(translated_prompt)
        if model == "stability"
        else generate_hf_image(translated_prompt)
    )

    if not image:
        await update.message.reply_text("Ошибка генерации. Попробуй другой запрос.")
        return MODEL_CHOICE

    await bot.delete_message(chat_id=update.effective_chat.id, message_id=status_msg.message_id)
    
    # Добавляем повторные попытки отправки фото
    max_retries = 3
    retry_delay = 2  # секунды
    
    for attempt in range(max_retries):
        try:
            await update.message.reply_photo(
                photo=image,
                caption=f"Запрос: {prompt}\n(Перевод: {translated_prompt})",
                reply_markup=ReplyKeyboardMarkup([
                    [KeyboardButton("Stability AI")],
                    [KeyboardButton("Hugging Face")]
                ], resize_keyboard=True)
            )
            break
        except telegram.error.TimedOut:
            if attempt < max_retries - 1:
                await asyncio.sleep(retry_delay)
                continue
            else:
                await update.message.reply_text(
                    "Не удалось отправить изображение из-за проблем с соединением. Попробуйте еще раз."
                )
                return MODEL_CHOICE
        except Exception as e:
            logger.error(f"Ошибка при отправке фото: {e}")
            await update.message.reply_text("Произошла ошибка при отправке изображения. Попробуйте еще раз.")
            return MODEL_CHOICE
            
    return MODEL_CHOICE

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Отмена действия."""
    await update.message.reply_text("Действие отменено. Выбери модель заново.")
    return MODEL_CHOICE

def main():
    """Запуск бота."""
    # Создаем приложение с увеличенным таймаутом
    app = Application.builder().token(CONFIG["TELEGRAM_TOKEN"]).connect_timeout(60).read_timeout(60).write_timeout(60).build()
    
    # Добавляем обработчик ошибок
    async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Обработчик ошибок."""
        logger.error("Exception while handling an update:", exc_info=context.error)
        
        if isinstance(context.error, telegram.error.TimedOut):
            if update and update.effective_message:
                await update.effective_message.reply_text(
                    "Произошла ошибка при отправке сообщения. Пожалуйста, попробуйте еще раз."
                )
        elif isinstance(context.error, telegram.error.Conflict):
            logger.warning("Conflict detected, waiting before retry...")
            # Ждем 5 секунд перед повторной попыткой
            await asyncio.sleep(5)
            # Очищаем очередь обновлений
            await context.bot.get_updates(offset=-1)
        else:
            if update and update.effective_message:
                await update.effective_message.reply_text(
                    "Произошла непредвиденная ошибка. Пожалуйста, попробуйте позже."
                )
    
    # Регистрируем обработчик ошибок
    app.add_error_handler(error_handler)
    
    app.add_handler(ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            MODEL_CHOICE: [MessageHandler(filters.Regex("^(Stability AI|Hugging Face)$"), handle_model_choice)],
            PROMPT_INPUT: [MessageHandler(filters.TEXT & ~filters.COMMAND, process_prompt)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    ))
    logger.info("Бот запущен!")
    
    # Запускаем бота с параметрами
    app.run_polling(
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=True,
        close_loop=False
    )

if __name__ == "__main__":
    main()
