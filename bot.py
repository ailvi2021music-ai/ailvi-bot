import os
import threading
from flask import Flask
from telegram.ext import ApplicationBuilder, MessageHandler, CommandHandler, filters
from openai import OpenAI

# -------------------------
# 🔑 API ключи
# -------------------------
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

client = OpenAI(api_key=OPENAI_API_KEY)

# -------------------------
# ✅ Flask health-check
# -------------------------
app = Flask(__name__)

@app.route("/")
def home():
    return "AILVI bot is alive"

def run_flask():
    app.run(host="0.0.0.0", port=10000)

# -------------------------
# ✅ Telegram logic
# -------------------------

async def handle_message(update, context):
    user_text = update.message.text

    # Создаём диалог с GPT
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": "Ты — мягкий, спокойный и добрый проводник AILVI. Ты помогаешь человеку распаковывать личность шаг за шагом, задаёшь вопросы, мягко направляешь и не отвечаешь за него."},
            {"role": "user", "content": user_text}
        ]
    )

    answer = response.choices[0].message["content"]
    await update.message.reply_text(answer)

async def start(update, context):
    await update.message.reply_text("Ассаламу Алейкум. Я готов работать с тобой.")


def run_telegram():
    application = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print("✅ Telegram polling started")
    application.run_polling()


# -------------------------
# ✅ Main section
# -------------------------
if __name__ == "__main__":
    # Запускаем Flask в отдельном потоке
    flask_thread = threading.Thread(target=run_flask)
    flask_thread.daemon = True
    flask_thread.start()

    # Запускаем Telegram бота
    run_telegram()
