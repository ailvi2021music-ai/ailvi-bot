import os
import threading
import asyncio
from flask import Flask, request
from telegram import Update
from telegram.ext import ApplicationBuilder, MessageHandler, CommandHandler, filters
from openai import OpenAI

# ----- ENV -----
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
# URL твоего сервиса на Render, без слеша в конце. Пример: https://ailvi-bot.onrender.com
WEBHOOK_BASE = os.getenv("WEBHOOK_BASE")  
# Секретный путь вебхука: сделай случайную строку (например, 24 символа)
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "supersecret_path_123")

client = OpenAI(api_key=OPENAI_API_KEY)

# ----- Flask (health + webhook) -----
app = Flask(__name__)

@app.get("/")
def health():
    return "AILVI bot is alive"

# Этот маршрут принимает апдейты от Telegram
@app.post(f"/{WEBHOOK_SECRET}")
def telegram_webhook():
    data = request.get_json(force=True)
    update = Update.de_json(data, application.bot)
    # Отдаём апдейт циклу PTB (он асинхронный)
    asyncio.run_coroutine_threadsafe(application.process_update(update), application.loop)
    return "ok"

def run_flask():
    # Render слушает 10000 порт на free инстансе
    app.run(host="0.0.0.0", port=10000)

# ----- Telegram handlers -----
async def start(update, context):
    await update.message.reply_text("Ассаламу Алейкум. Я готов работать с тобой.")

async def handle_message(update, context):
    user_text = update.message.text

    resp = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": "Ты — мягкий, спокойный и добрый проводник AILVI. Помогаешь распаковывать личность, задаёшь уточняющие вопросы и не отвечаешь за человека."},
            {"role": "user", "content": user_text}
        ]
    )
    # openai-python v1: контент находится здесь:
    answer = resp.choices[0].message.content
    await update.message.reply_text(answer)

# Создаём приложение PTB (без polling)
application = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()
application.add_handler(CommandHandler("start", start))
application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

async def init_telegram():
    # Инициализируем PTB и ставим webhook
    await application.initialize()
    await application.start()
    # Сбрасываем хвосты и ставим новый вебхук
    await application.bot.set_webhook(
        url=f"{WEBHOOK_BASE}/{WEBHOOK_SECRET}",
        drop_pending_updates=True,
        allowed_updates=["message"]  # экономим трафик, если нужны только сообщения
    )

if __name__ == "__main__":
    # 1) Запускаем Telegram-часть (инициализация + webhook)
    asyncio.run(init_telegram())

    # 2) Поднимаем Flask (HTTP-сервер для вебхука и health)
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()

    # 3) Держим главный поток живым
    flask_thread.join()
