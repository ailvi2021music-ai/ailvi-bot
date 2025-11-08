import os
import threading
from flask import Flask
from telegram.ext import ApplicationBuilder, MessageHandler, CommandHandler, filters
from openai import OpenAI

# -------------------------
# 🔑 Ключи
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
    # ВАЖНО: запрещаем reloader, чтобы процесс не запускался повторно
    app.run(host="0.0.0.0", port=10000, debug=False, use_reloader=False, threaded=True)

# -------------------------
# ✅ Telegram logic
# -------------------------
WELCOME_TEXT = (
    "Ассаляму Алейкум уа РахматуЛлахи уа Баракятух! 👋🏻\n\n"
    "Добро пожаловать в пространство, где Сердце узнаёт себя заново.\n\n"
    "Давай вместе, спокойно, шаг за шагом откроем драгоценные дары, которые Аллах уже вложил "
    "в твою Душу — силы, таланты, намерения, которые ждут, когда ты увидишь их Свет. 💎\n\n"
    "Пусть Аллах сделает этот путь лёгким, благословенным и наполненным пониманием!\n\n"
    "Напиши любую фразу — и я начну диалог с тобой."
)

async def start(update, context):
    await update.message.reply_text(WELCOME_TEXT)

async def handle_message(update, context):
    user_text = update.message.text

    response = client.chat.completions.create(
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
    # openai==1.3.7 возвращает dict в .message
    answer = response.choices[0].message["content"]
    await update.message.reply_text(answer)

def run_telegram():
    application = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    print("✅ Telegram polling started")
    application.run_polling()

# -------------------------
# ✅ Main
# -------------------------
if __name__ == "__main__":
    # Запускаем Flask в отдельном потоке
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()

    # Запускаем Telegram бота (единожды)
    run_telegram()
