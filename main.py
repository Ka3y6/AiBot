import logging
import base64
from io import BytesIO
import requests
import os
from dotenv import load_dotenv
import asyncio
import telegram
import sys
from logging.handlers import RotatingFileHandler

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

# Настраиваем логирование
logger = logging.getLogger("ImageGenBot")
logger.setLevel(logging.DEBUG)

# Форматирование логов
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')

# Вывод в консоль
console_handler = logging.StreamHandler(sys.stdout)
console_handler.setLevel(logging.INFO)
console_handler.setFormatter(formatter)
logger.addHandler(console_handler)

# Вывод в файл с ротацией (максимум 5 файлов по 2 МБ)
try:
    file_handler = RotatingFileHandler('bot.log', maxBytes=2*1024*1024, backupCount=5)
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    logger.info("Логирование в файл настроено")
except Exception as e:
    logger.warning(f"Не удалось настроить логирование в файл: {e}")

# Получаем API ключи из переменных окружения или используем значения по умолчанию
stability_api_key = os.getenv("STABILITY_API_KEY", "sk-6gniSvAdfLZRmhpfC3Pjzzl7KkXkvBSOyATCfb5RwCcxnsov")

CONFIG = {
    "TELEGRAM_TOKEN": os.getenv("TELEGRAM_TOKEN"),
    "STABILITY_API_KEY": stability_api_key,
    "HF_TOKEN": os.getenv("HF_TOKEN")
}

# Проверяем наличие всех необходимых токенов
if not CONFIG["TELEGRAM_TOKEN"]:
    logger.critical("Отсутствует токен Telegram в переменных окружения")
    sys.exit(1)
if not CONFIG["STABILITY_API_KEY"]:
    logger.warning("Отсутствует ключ Stability API в переменных окружения")
if not CONFIG["HF_TOKEN"]:
    logger.warning("Отсутствует токен Hugging Face в переменных окружения")

logger.info("Конфигурация загружена успешно")

MODEL_CHOICE, PROMPT_INPUT = range(2)

bot = Bot(token=CONFIG["TELEGRAM_TOKEN"])

def generate_stability_image(prompt: str) -> BytesIO | None:
    """Генерация через Stability AI."""
    # Список доступных движков в порядке предпочтения
    engines = [
        "stable-diffusion-xl-1024-v1-0",  # Первая доступная модель
        "stable-diffusion-v1-6"           # Вторая доступная модель
    ]
    
    # Проверяем API ключ
    if not CONFIG["STABILITY_API_KEY"]:
        logger.error("Отсутствует ключ Stability API")
        return None
        
    # Пробуем каждый движок по очереди
    for engine in engines:
        try:
            logger.info(f"Отправка запроса в Stability AI с промптом: {prompt}, движок: {engine}")
            
            # Проверяем версию API
            api_host = os.getenv('STABILITY_HOST', 'https://api.stability.ai')
            
            # Настраиваем размеры в зависимости от движка
            height = 1024 if "1024" in engine or "xl" in engine.lower() else 512
            width = 1024 if "1024" in engine or "xl" in engine.lower() else 512
            
            # Отправляем запрос
            response = requests.post(
                f"{api_host}/v1/generation/{engine}/text-to-image",
                headers={
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                    "Authorization": f"Bearer {CONFIG['STABILITY_API_KEY']}"
                },
                json={
                    "text_prompts": [
                        {
                            "text": prompt,
                            "weight": 1.0
                        }
                    ],
                    "cfg_scale": 7.0,
                    "height": height,
                    "width": width,
                    "samples": 1,
                    "steps": 30
                },
                timeout=40
            )
            
            logger.info(f"Получен ответ от Stability AI. Статус: {response.status_code}")
            
            if response.status_code == 401:
                logger.error("Недействительный API ключ Stability AI или недостаточно кредитов")
                return None
                
            if not response.ok:
                logger.error(f"Ошибка Stability API для движка {engine}: {response.status_code} - {response.text}")
                continue  # Пробуем следующий движок
                
            # Проверяем содержимое ответа
            try:
                json_response = response.json()
                logger.info(f"Получен JSON ответ от Stability API: {json_response.keys()}")
                
                if "artifacts" in json_response and json_response["artifacts"]:
                    logger.info(f"Найдены артефакты в ответе для движка {engine}, декодируем изображение")
                    image_data = base64.b64decode(json_response["artifacts"][0]["base64"])
                    return BytesIO(image_data)
                else:
                    logger.error(f"Отсутствуют артефакты в ответе для движка {engine}: {json_response}")
                    continue  # Пробуем следующий движок
            except Exception as e:
                logger.error(f"Ошибка при обработке JSON ответа для движка {engine}: {e}", exc_info=True)
                logger.error(f"Содержимое ответа: {response.text[:200]}")
                continue  # Пробуем следующий движок
                
        except Exception as e:
            logger.error(f"Stability AI error для движка {engine}: {e}", exc_info=True)
            continue  # Пробуем следующий движок
    
    # Если все движки не сработали
    logger.error("Все движки Stability AI не смогли сгенерировать изображение")
    return None

def generate_hf_image(prompt: str) -> BytesIO | None:
    """Генерация через Hugging Face."""
    try:
        logger.info(f"Отправка запроса в Hugging Face с промптом: {prompt}")
        
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
        
        logger.info(f"Получен ответ от Hugging Face. Статус: {response.status_code}")
        
        if not response.ok:
            logger.error(f"Ошибка Hugging Face API: {response.status_code} - {response.text}")
            return None
            
        try:
            json_data = response.json()
            logger.info("Успешно получен JSON ответ от Hugging Face")
            
            if "data" not in json_data or not json_data["data"]:
                logger.error(f"Отсутствует поле 'data' в ответе: {json_data}")
                return None
                
            if "b64_json" not in json_data["data"][0]:
                logger.error(f"Отсутствует поле 'b64_json' в ответе: {json_data['data'][0]}")
                return None
                
            img_data = json_data["data"][0]["b64_json"]
            logger.info("Успешно извлечены данные изображения, декодируем base64")
            return BytesIO(base64.b64decode(img_data))
            
        except Exception as e:
            logger.error(f"Ошибка при обработке JSON ответа: {e}", exc_info=True)
            return None
            
    except Exception as e:
        logger.error(f"Hugging Face error: {e}", exc_info=True)
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
    logger.info(f"Выбрана модель: {model}")
    
    translated_prompt = translate_prompt(prompt)
    logger.info(f"Исходный промпт: '{prompt}', переведенный: '{translated_prompt}'")
    
    status_msg = await update.message.reply_text("Генерация...")

    logger.info(f"Начинаем генерацию изображения с моделью {model}")
    
    # Сначала пробуем выбранную модель
    image = (
        generate_stability_image(translated_prompt)
        if model == "stability"
        else generate_hf_image(translated_prompt)
    )
    
    # Если Stability API не работает, попробуем Hugging Face
    if not image and model == "stability" and CONFIG["HF_TOKEN"]:
        logger.info("Stability API недоступен, пробуем Hugging Face как запасной вариант")
        await update.message.reply_text("Stability AI временно недоступен, использую Hugging Face...")
        image = generate_hf_image(translated_prompt)

    if not image:
        logger.error(f"Генерация изображения не удалась для промпта: '{prompt}'")
        await update.message.reply_text("Ошибка генерации. Попробуйте другой запрос.")
        return MODEL_CHOICE

    logger.info("Изображение успешно сгенерировано, отправляем пользователю")
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
    logger.info("Инициализация бота...")
    
    # Создаем приложение с увеличенным таймаутом
    app = Application.builder().token(CONFIG["TELEGRAM_TOKEN"]).connect_timeout(60).read_timeout(60).write_timeout(60).build()
    logger.info("Приложение создано с увеличенными таймаутами")
    
    # Добавляем обработчик ошибок
    async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Обработчик ошибок."""
        logger.error("Exception while handling an update:", exc_info=context.error)
        
        if isinstance(context.error, telegram.error.TimedOut):
            logger.warning("Обнаружена ошибка таймаута Telegram API")
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
            logger.error(f"Неизвестная ошибка: {type(context.error).__name__}: {context.error}")
            if update and update.effective_message:
                await update.effective_message.reply_text(
                    "Произошла непредвиденная ошибка. Пожалуйста, попробуйте позже."
                )
    
    # Регистрируем обработчик ошибок
    app.add_error_handler(error_handler)
    logger.info("Обработчик ошибок зарегистрирован")
    
    # Добавляем обработчики команд
    logger.info("Регистрация обработчиков команд...")
    app.add_handler(ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            MODEL_CHOICE: [MessageHandler(filters.Regex("^(Stability AI|Hugging Face)$"), handle_model_choice)],
            PROMPT_INPUT: [MessageHandler(filters.TEXT & ~filters.COMMAND, process_prompt)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    ))
    logger.info("Обработчики команд зарегистрированы")
    
    logger.info("Бот запущен! Ожидание сообщений...")
    
    # Запускаем бота с параметрами
    app.run_polling(
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=True,
        close_loop=False
    )

if __name__ == "__main__":
    main()
