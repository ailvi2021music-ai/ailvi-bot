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

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {
                "role": "system",
                "content": (
                    "Ты — мягкий, спокойный, внимательный проводник. "
                    "Помогаешь человеку раскрывать личность, задавая вопросы, поддерживая и направляя."
                )
            },
            {"role": "user", "content": user_text}
        ]
    )

    answer = response.choices[0].message["content"]
    await update.message.reply_text(answer)

async def start(update, context):
    greeting = (
        "Ассаляму Алейкум уа РахматуЛлахи уа Баракятух! 👋🏻\n\n"
        "Добро пожаловать в пространство, где Сердце узнаёт себя заново.\n\n"
        "Давай вместе, спокойно, шаг за шагом откроем драгоценные дары, которые Аллах уже вложил в твою Душу — "
        "силы, таланты, намерения, которые ждут, когда ты увидишь их Свет. 💎\n\n"
        "Пусть Аллах сделает этот путь лёгким, благословенным и наполненным пониманием! 🚀\n\n"
        "Напиши пару слов о себе — и мы начнём."
    )
    await update.message.reply_text(greeting)


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
    flask_thread = threading.Thread(target=run_flask)
    flask_thread.daemon = True
    flask_thread.start()

    run_telegram()
