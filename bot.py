import os
import threading
from flask import Flask
from telegram.ext import ApplicationBuilder, MessageHandler, CommandHandler, filters
from openai import OpenAI

# -------------------------
# 🔑 Ключи из переменных окружения
# -------------------------
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

client = OpenAI(api_key=OPENAI_API_KEY)

# -------------------------
# ✅ Flask health-check (для Render)
# -------------------------
app = Flask(__name__)

@app.route("/")
def home():
    return "AILVI bot is alive"

def run_flask():
    # Порт 10000 — как и раньше
    app.run(host="0.0.0.0", port=10000)

# -------------------------
# ✅ Telegram logic
# -------------------------

async def handle_message(update, context):
    # Пропускаем не-текстовые апдейты
    if not update.message or not update.message.text:
        return

    user_text = update.message.text.strip()

    try:
        # Диалог с GPT
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Ты — мягкий, спокойный и добрый проводник AILVI. "
                        "Ты помогаешь человеку распаковывать личность шаг за шагом, "
                        "задаёшь вопросы, мягко направляешь и не отвечаешь за него."
                    ),
                },
                {"role": "user", "content": user_text},
            ],
        )

        # ВАЖНО: в SDK v1 берём message.content, а не ["content"]
        answer = resp.choices[0].message.content if resp.choices else "…"

        await update.message.reply_text(answer or "…")

    except Exception as e:
        # Неброский ответ, чтобы бот не падал из-за исключений
        await update.message.reply_text("Извини, сейчас я чуть задумался. Попробуй ещё раз.")
        # Можно залогировать в stdout, Render это покажет в логах
        print(f"[ERROR] handle_message: {e}")

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
