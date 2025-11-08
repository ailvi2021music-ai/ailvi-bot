import logging
from telegram import Update
from telegram.ext import Updater, CommandHandler, MessageHandler, Filters, CallbackContext
import openai

TELEGRAM_TOKEN = "ТВОЙ_ТОКЕН"
OPENAI_API_KEY = "ТВОЙ_API_KEY"

openai.api_key = OPENAI_API_KEY

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

def start(update: Update, context: CallbackContext):
    update.message.reply_text(
        "Ассаляму Алейкум уа РахматуЛлахи уа Баракятух! 👋🏻\n\n"
        "Добро пожаловать в пространство, где Сердце узнаёт себя заново.\n\n"
        "Чтобы начать — просто напиши любое слово."
    )

def chat(update: Update, context: CallbackContext):
    user_msg = update.message.text

    response = openai.Completion.create(
        model="gpt-3.5-turbo-instruct",
        prompt=user_msg,
        max_tokens=200
    )

    answer = response["choices"][0]["text"].strip()
    update.message.reply_text(answer)

def main():
    updater = Updater(TELEGRAM_TOKEN, use_context=True)
    dp = updater.dispatcher

    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(MessageHandler(Filters.text & ~Filters.command, chat))

    updater.start_polling()
    updater.idle()

if __name__ == "__main__":
    main()
