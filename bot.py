import os
import asyncio
import httpx
from flask import Flask, request
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters
from openai import OpenAI

# ---- Env ----
OPENAI_API_KEY   = os.getenv("OPENAI_API_KEY")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
WEBHOOK_BASE     = os.getenv("WEBHOOK_BASE")      # например: https://ailvi-bot.onrender.com
WEBHOOK_SECRET   = os.getenv("WEBHOOK_SECRET")    # например: ailvi_secret_123

client = OpenAI(api_key=OPENAI_API_KEY)

# ---- Telegram application (без polling) ----
application = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()

async def start(update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Ассаламу Алейкум. Я рядом и веду тебя шаг за шагом.")

async def handle_message(update, context: ContextTypes.DEFAULT_TYPE):
    user_text = update.message.text
    resp = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": "Ты — мягкий проводник AILVI. Задаёшь вопросы и раскрываешь человека."},
            {"role": "user", "content": user_text},
        ],
    )
    answer = resp.choices[0].message["content"]
    await update.message.reply_text(answer)

application.add_handler(CommandHandler("start", start))
application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

# ---- Flask ----
app = Flask(__name__)

@app.post(f"/{WEBHOOK_SECRET}")
def webhook():
    """Синхронный Flask-роут, внутри запускаем async-обработку."""
    data = request.get_json(force=True, silent=True) or {}
    update = Update.de_json(data, application.bot)
    asyncio.run(application.process_update(update))
    return "ok"

@app.get("/")
def health():
    return "AILVI bot is alive"

def set_webhook():
    """Ставим вебхук через Telegram API (надёжно и просто)."""
    url = f"{WEBHOOK_BASE}/{WEBHOOK_SECRET}"
    api = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/setWebhook"
    with httpx.Client(timeout=10.0) as x:
        r = x.post(api, json={"url": url})
        print("SetWebhook status:", r.status_code, r.text)

if __name__ == "__main__":
    # 1) Перед запуском сервера ставим вебхук
    set_webhook()
    # 2) Запускаем Flask на Render-порту 10000
    app.run(host="0.0.0.0", port=10000)
