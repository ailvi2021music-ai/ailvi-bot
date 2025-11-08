import os
import asyncio
import threading
from flask import Flask
from openai import OpenAI
from telegram import Update
from telegram.error import Conflict
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

# ============== ENV ==============
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

client = OpenAI(api_key=OPENAI_API_KEY)

# ============== Flask health-check ==============
app = Flask(__name__)

@app.route("/")
def home():
    return "AILVI bot is alive"

def run_flask():
    # Render pings порт 10000
    app.run(host="0.0.0.0", port=10000)

# ============== Telegram handlers ==============
START_TEXT = (
    "Ассаляму Алейкум уа РахматуЛлахи уа Баракятух! 👋🏻\n\n"
    "Добро пожаловать в пространство, где Сердце узнаёт себя заново.\n\n"
    "Давай вместе, спокойно, шаг за шагом откроем драгоценные дары, которые Аллах уже вложил в твою Душу — "
    "силы, таланты, намерения, которые ждут, когда ты увидишь их Свет. 💎\n\n"
    "Пусть Аллах сделает этот путь лёгким, благословенным и наполненным пониманием!\n\n"
    "Чтобы мы начали, просто напиши мне любое слово — и я мягко поведу тебя дальше."
)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(START_TEXT)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_text = update.message.text or ""

    # Диалог с GPT
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {
                "role": "system",
                "content": (
                    "Ты — мягкий, спокойный и добрый проводник AILVI. "
                    "Помогаешь человеку распаковывать личность шаг за шагом, задаёшь вопросы, "
                    "мягко направляешь и не отвечаешь за него."
                ),
            },
            {"role": "user", "content": user_text},
        ],
    )

    # Для openai==1.3.7 доступ через словарь:
    answer = response.choices[0].message["content"]
    await update.message.reply_text(answer)

# ============== Telegram bootstrap (robust) ==============
async def run_telegram_async():
    application = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()

    # Убираем возможный webhook и чистим старые очереди,
    # чтобы пуллинг точно был единственным источником апдейтов
    try:
        await application.bot.delete_webhook(drop_pending_updates=True)
    except Exception:
        pass  # если вебхука не было — ок

    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    # Защита от редкой гонки при деплое: перезапуск при Conflict
    try:
        await application.run_polling(close_loop=False)
    except Conflict:
        # Короткая пауза и вторая попытка — когда прежняя копия окончательно освободит токен
        await asyncio.sleep(12)
        await application.run_polling(close_loop=False)

def run_telegram():
    asyncio.run(run_telegram_async())

# ============== Main ==============
if __name__ == "__main__":
    # Flask в отдельном потоке (для Render health-check)
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()

    # Telegram-бот (единственная копия процесса)
    run_telegram()
