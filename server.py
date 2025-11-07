import os
import threading
from flask import Flask
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters
)
from openai import OpenAI

# Секреты из Render
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

client = OpenAI(api_key=OPENAI_API_KEY)
flask_app = Flask(__name__)

# === ОБРАБОТЧИКИ ===
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
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

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Ассаляму Алейкум. Я готов работать.")

# === ЗАПУСК TELEGRAM ===
def run_telegram_bot():
    application = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print("✅ Telegram polling started")
    application.run_polling()

# === HEALTHCHECK ДЛЯ RENDER ===
@flask_app.get("/")
def health():
    return "OK", 200

# === ГЛАВНЫЙ СТАРТ ===
if __name__ == "__main__":
    # Telegram в отдельном потоке
    t = threading.Thread(target=run_telegram_bot, daemon=True)
    t.start()

    port = int(os.getenv("PORT", 10000))
    print(f"✅ Flask health server on port {port}")
    flask_app.run(host="0.0.0.0", port=port)
