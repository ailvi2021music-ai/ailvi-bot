import os
import threading
from flask import Flask
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters
from openai import OpenAI

# Секреты приходят из переменных окружения Render
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

client = OpenAI(api_key=OPENAI_API_KEY)
flask_app = Flask(__name__)

async def handle_message(update: Update, context):
    user_text = (update.message.text or "").strip()

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": "You are AILVI — a gentle guide who helps a person unpack themselves."},
            {"role": "user", "content": user_text},
        ]
    )
    answer = response.choices[0].message["content"]
    await update.message.reply_text(answer)

async def start(update: Update, context):
    await update.message.reply_text("Ассаляму Алейкум. Я готов работать.")

def run_telegram_bot():
    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    print("Telegram polling started.")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

@flask_app.get("/")
def healthcheck():
    return "OK", 200

if __name__ == "__main__":
    # Telegram-бот в отдельном потоке
    t = threading.Thread(target=run_telegram_bot, daemon=True)
    t.start()

    # Мини-веб-сервер для Render (health check)
    port = int(os.getenv("PORT", 10000))
    print(f"HTTP health server on port {port}")
    flask_app.run(host="0.0.0.0", port=port)
