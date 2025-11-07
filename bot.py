import os
from telegram.ext import Updater, MessageHandler, Filters, CommandHandler
from openai import OpenAI

# Загружаем токены из переменных окружения Render
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

# Инициализация клиента OpenAI
client = OpenAI(api_key=OPENAI_API_KEY)

# Счётчики сообщений пользователей
user_message_count = {}

# Приветственный текст
WELCOME_TEXT = (
    "Ассаляму Алейкум уа РахматуЛлахи уа Баракятух! 👋🏻\n\n"
    "Добро пожаловать в пространство, где Сердце узнаёт себя заново.\n\n"
    "Давай вместе, спокойно, шаг за шагом откроем драгоценные дары, которые Аллах уже вложил "
    "в твою Душу — силы, таланты, намерения, которые ждут, когда ты увидишь их Свет. 💎\n\n"
    "Пусть Аллах сделает этот путь лёгким, благословенным и наполненным пониманием!\n\n"
    "Чтобы начать — просто напиши любое слово. Я рядом."
)

# Команда /start
def start(update, context):
    chat_id = update.message.chat_id
    user_message_count[chat_id] = 0
    update.message.reply_text(WELCOME_TEXT)

# Обработка всех текстовых сообщений
def handle_message(update, context):
    chat_id = update.message.chat_id
    text = update.message.text

    # Увеличиваем счётчик сообщений
    user_message_count[chat_id] = user_message_count.get(chat_id, 0) + 1

    # GPT-5 ответ
    completion = client.chat.completions.create(
        model="gpt-5",
        messages=[
            {
                "role": "system",
                "content": (
                    "Ты — мягкий наставник в стиле AILVI: вдохновляющий, спокойный, глубоко "
                    "понимающий человека, говорящий сердцем и ведя к раскрытию внутреннего дара."
                )
            },
            {"role": "user", "content": text}
        ]
    )

    reply = completion.choices[0].message.content
    update.message.reply_text(reply)

# Главная функция
def main():
    updater = Updater(TELEGRAM_BOT_TOKEN, use_context=True)
    dp = updater.dispatcher

    # обработчики
    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(MessageHandler(Filters.text & ~Filters.command, handle_message))

    # запуск long-polling
    updater.start_polling()
    updater.idle()

# Запуск
if __name__ == "__main__":
    main()
