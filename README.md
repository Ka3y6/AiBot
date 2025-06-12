# AiBot - Telegram бот для генерации изображений

Telegram бот, который генерирует изображения с помощью Stability AI и Hugging Face API.

## Возможности

- Генерация изображений через Stability AI
- Генерация изображений через Hugging Face
- Автоматический перевод промптов с русского на английский
- Интерактивный интерфейс с кнопками

## Установка

1. Клонируйте репозиторий:
```bash
git clone https://github.com/Ka3y6/AiBot.git
cd AiBot
```

2. Установите зависимости:
```bash
pip install -r requirements.txt
```

3. Создайте файл `.env` и добавьте необходимые токены:
```
TELEGRAM_TOKEN=ваш_токен_телеграм
STABILITY_API_KEY=ваш_ключ_stability
HF_TOKEN=ваш_токен_huggingface
```

## Запуск

```bash
python main.py
```

## Использование

1. Отправьте команду `/start` боту
2. Выберите модель генерации (Stability AI или Hugging Face)
3. Отправьте описание желаемого изображения
4. Дождитесь генерации и получите результат

## Требования

- Python 3.8+
- python-telegram-bot>=20.0
- requests>=2.31.0
- python-dotenv==1.0.0
- deep-translator==1.11.4
- Pillow==10.0.0

## Лицензия

MIT 