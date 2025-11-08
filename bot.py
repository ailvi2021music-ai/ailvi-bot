import logging
from telegram.ext import Updater, CommandHandler, MessageHandler, Filters
import openai
import os

# ЛОГИ
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

# КЛЮЧИ
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
openai.api_key = OPENAI_API_KEY


# -----------------------------
#   ОБРАБОТКА /start
# -----------------------------
def start(update, context):
    update.message.reply_text(
        "Ассаляму Алейкум уа РахматуЛлахи уа Баракятух! 🌿\n\n"
        "Добро пожаловать 🙌\n\n"
        "Чтобы начать путешествие — просто напиши мне любое сообщение."
    )


# -----------------------------
#   ПЕРЕДАЧА СООБЩЕНИЯ В GPT
# -----------------------------
def handle_message(update, context):
    user_text = update.message.text

    try:
        response = openai.ChatCompletion.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "Ты — добрый наставник AILVI."},
                {"role": "user", "content": user_text}
            ]
        )

        bot_reply = response["choices"][0]["message"]["content"]
        update.message.reply_text(bot_reply)

    except Exception as e:
        update.message.reply_text("Произошла ошибка. Попробуй ещё раз.")
        print(e)


# -----------------------------
#   ЗАПУСК БОТА
# -----------------------------
def main():
    updater = Updater(TELEGRAM_TOKEN, use_context=True)
    dp = updater.dispatcher

    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(MessageHandler(Filters.text & ~Filters.command, handle_message))

    updater.start_polling()
    updater.idle()


if name == "__main__":
    main()
