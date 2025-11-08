# bot.py
import os
import threading
from flask import Flask
from telegram.ext import ApplicationBuilder, MessageHandler, CommandHandler, filters
from openai import OpenAI

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

client = OpenAI(api_key=OPENAI_API_KEY)

# ---- health-check для Render ----
app = Flask(__name__)

@app.route("/")
def home():
    return "AILVI bot is alive"

def run_flask():
    app.run(host="0.0.0.0", port=10000)

# ---- Telegram ----
async def handle_message(update, context):
    user_text = update.message.text
    resp = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system",
             "content": "Ты — мягкий, спокойный и добрый проводник AILVI. "
                        "Помогаешь человеку распаковывать личность шаг за шагом, "
                        "задаёшь вопросы, мягко направляешь и не отвечаешь за него."},
            {"role": "user", "content": user_text}
        ]
    )
    answer = resp.choices[0].message["content"]
    await update.message.reply_text(answer)

async def start(update, context):
    await update.message.reply_text("Ассаламу Алейкум. Я готов работать с тобой.")

# ВАЖНО: авто-снятие вебхука перед polling
async def _post_init(app):
    await app.bot.delete_webhook(drop_pending_updates=True)

def run_telegram():
    application = (
        ApplicationBuilder()
        .token(TELEGRAM_BOT_TOKEN)
        .post_init(_post_init)   # <— добавили
        .build()
    )
    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    print("✅ Telegram polling started")
    application.run_polling()

if __name__ == "__main__":
    t = threading.Thread(target=run_flask, daemon=True)
    t.start()
    run_telegram()
