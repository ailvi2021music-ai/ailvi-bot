import os
import threading
from flask import Flask
from telegram import Update
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters
)
from openai import OpenAI

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

client = OpenAI(api_key=OPENAI_API_KEY)
flask_app = Flask(__name__)

# -------- Telegram handlers --------
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

def build_application():
    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    return app

# -------- Health endpoint for Render --------
@flask_app.get("/")
def health():
    return "OK", 200

def run_flask():
    port = int(os.getenv("PORT", 10000))
    print(f"✅ Flask health server on port {port}")
    flask_app.run(host="0.0.0.0", port=port)

if __name__ == "__main__":
    # 1) Запускаем Flask в фоновом потоке
    threading.Thread(target=run_flask, daemon=True).start()

    # 2) Telegram-пуллинг запускаем в ГЛАВНОМ потоке (так корректно для asyncio)
    application = build_application()
    print("✅ Telegram polling started")
    application.run_polling()
