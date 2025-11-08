import os
from flask import Flask, request
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes
from openai import OpenAI

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
WEBHOOK_BASE = os.getenv("WEBHOOK_BASE")
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET")

client = OpenAI(api_key=OPENAI_API_KEY)

app = Flask(__name__)

# ----------------------------
# ✅ Обработка Telegram webhook
# ----------------------------
@app.post(f"/{WEBHOOK_SECRET}")
async def webhook():
    data = request.json
    update = Update.de_json(data, application.bot)
    await application.process_update(update)
    return "ok"


# ----------------------------
# ✅ Команды и сообщения
# ----------------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Ассаламу Алейкум. Я рядом, и я буду вести тебя шаг за шагом.")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_text = update.message.text

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": "Ты — мягкий проводник AILVI. Ты задаёшь вопросы, раскрываешь человека, а не отвечаешь вместо него."},
            {"role": "user", "content": user_text}
        ]
    )
    answer = response.choices[0].message["content"]
    await update.message.reply_text(answer)


# ----------------------------
# ✅ Запуск Telegram приложения
# ----------------------------
application = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()
application.add_handler(CommandHandler("start", start))
application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))


# ----------------------------
# ✅ Установка webhook при старте
# ----------------------------
@app.before_first_request
def setup_webhook():
    url = f"{WEBHOOK_BASE}/{WEBHOOK_SECRET}"
    print("Setting webhook to:", url)
    application.bot.set_webhook(url)


# ----------------------------
# ✅ Запуск Flask сервера
# ----------------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
