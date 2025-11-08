import os
import threading
from flask import Flask
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,   # <- вместо Filters
)
from openai import OpenAI

# === Настройки окружения ===
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

client = OpenAI(api_key=OPENAI_API_KEY)

# === Health-check для Render ===
web = Flask(__name__)

@web.route("/")
def health():
    return "OK", 200

def run_health_server():
    # Render пингует порт 10000
    web.run(host="0.0.0.0", port=10000)

# === Телеграм-обработчики ===
WELCOME_TEXT = (
    "Ассаляму Алейкум уа РахматуЛлахи уа Баракятух! 👋🏻\n\n"
    "Добро пожаловать в пространство, где Сердце узнаёт себя заново.\n\n"
    "Давай вместе, спокойно, шаг за шагом откроем драгоценные дары, которые Аллах уже вложил в твою Душу — "
    "силы, таланты, намерения, которые ждут, когда ты увидишь их Свет. 💎\n\n"
    "Пусть Аллах сделает этот путь лёгким, благословенным и наполненным пониманием!\n\n"
    "Чтобы начать работу, просто напиши готов (или опиши свой запрос)."
)

SYSTEM_PROMPT = (
    "Ты — AILVI, мягкий и чуткий проводник. Помогаешь человеку распаковать сильные стороны, таланты, "
    "и подобрать 3 подходящих направления заработка. Пиши коротко, по делу и доброжелательно. "
    "Русский язык."
)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(WELCOME_TEXT, parse_mode="Markdown")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_text = update.message.text.strip()

    # Вызов OpenAI (chat.completions совместим с openai==1.37.0)
    resp = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_text},
        ],
        temperature=0.5,
    )
    answer = resp.choices[0].message["content"]
    await update.message.reply_text(answer)

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("Напиши «готов» или сформулируй запрос — и двинемся дальше.")

def main() -> None:
    # Поднимаем health-сервер в отдельном потоке
    threading.Thread(target=run_health_server, daemon=True).start()

    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    app.run_polling(close_loop=False)

if name == "__main__":
    main()
