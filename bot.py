# bot.py
import os
import threading
import logging
from flask import Flask
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    ContextTypes,
    CommandHandler,
    MessageHandler,
    filters,
)
from openai import OpenAI

# -------------------------
# 🔧 Логи
# -------------------------
logging.basicConfig(
    format="%(asctime)s %(levelname)s %(name)s | %(message)s",
    level=logging.INFO,
)
log = logging.getLogger("ailvi-bot")

# -------------------------
# 🔑 Переменные окружения
# -------------------------
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

if not OPENAI_API_KEY:
    raise RuntimeError("OPENAI_API_KEY не найден в переменных окружения")
if not TELEGRAM_BOT_TOKEN:
    raise RuntimeError("TELEGRAM_BOT_TOKEN не найден в переменных окружения")

# ВАЖНО: новый SDK берёт ключ из окружения, параметр api_key передавать не нужно
client = OpenAI()

# -------------------------
# ✅ Health-check (Render)
# -------------------------
app = Flask(__name__)

@app.route("/")
def home():
    return "AILVI bot is alive"

def run_flask():
    # Render смотрит порт 10000
    app.run(host="0.0.0.0", port=10000)

# -------------------------
# 🤖 Telegram-логика
# -------------------------

# post_init вызывается ПЕРЕД стартом polling:
# удаляем webhook и сбрасываем «висящие» апдейты,
# чтобы не было конфликтов "other getUpdates request"
async def post_init(application):
    try:
        await application.bot.delete_webhook(drop_pending_updates=True)
        log.info("Webhook удалён, pending updates сброшены")
    except Exception as e:
        log.warning("Не удалось удалить webhook: %s", e)

ASYNC_SYSTEM_PROMPT = (
    "Ты — мягкий, спокойный и добрый проводник AILVI. "
    "Помогаешь человеку распаковывать личность шаг за шагом, задаёшь уточняющие вопросы, "
    "бережно направляешь и не придумываешь ответы за человека."
)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Ассаламу Алейкум. Я готов работать с тобой."
    )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return

    user_text = update.message.text.strip()

    try:
        # Новый SDK: chat.completions.create
        completion = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": ASYNC_SYSTEM_PROMPT},
                {"role": "user", "content": user_text},
            ],
            temperature=0.5,
        )
        # ВАЖНО: теперь доступ к тексту так:
        answer = completion.choices[0].message.content
        if not answer:
            answer = "Мне сложно сформулировать ответ. Скажи, пожалуйста, иначе."
        await update.message.reply_text(answer)

    except Exception as e:
        log.exception("Ошибка OpenAI: %s", e)
        await update.message.reply_text(
            "Похоже, возникла техническая пауза. Попробуй написать ещё раз через минуту."
        )

def run_telegram():
    application = (
        ApplicationBuilder()
        .token(TELEGRAM_BOT_TOKEN)
        .post_init(post_init)  # удалим webhook перед polling
        .build()
    )

    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    log.info("✅ Telegram polling started")
    # drop_pending_updates=True ещё раз на всякий случай
    application.run_polling(close_loop=False, drop_pending_updates=True)

# -------------------------
# 🚀 Main
# -------------------------
if __name__ == "__main__":
    # 1) поднимаем health-check сервер (Render ждёт ответ на порт 10000)
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()

    # 2) запускаем Telegram-бота (polling)
    run_telegram()
