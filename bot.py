# bot.py
import os
import logging

from telegram.ext import Updater, CommandHandler, MessageHandler, Filters

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

SYSTEM_PROMPT = (
    "You are AILVI — a gentle, practical guide who помогает человеку распаковать "
    "сильные стороны и наметить пути заработка на них. Отвечай коротко, по делу, "
    "бережно и ясно."
)

WELCOME_TEXT = (
    "Ассаляму Алейкум уа РахматуЛлахи уа Баракятух! 👋🏻\n\n"
    "Добро пожаловать в пространство, где Сердце узнаёт себя заново.\n\n"
    "Спокойно и шаг за шагом откроем дары, которые Аллах уже вложил в твою Душу — "
    "силы, таланты, намерения. 💎\n\n"
    "Чтобы начать — просто напиши мне любое сообщение."
)

def start(update, context):
    update.message.reply_text(WELCOME_TEXT)

def _ask_openai(user_text: str) -> str:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return "⚠️ Не найден OPENAI_API_KEY в переменных окружения."

    # Пытаемся работать и с новым SDK, и со старым — что установлено, тем и пользуемся.
    try:
        try:
            # Новый SDK (openai>=1.x)
            from openai import OpenAI
            client = OpenAI(api_key=api_key)
            resp = client.chat.completions.create(
                model="gpt-5-chat-latest",
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_text},
                ],
                temperature=0.7,
                max_tokens=400,
            )
            return resp.choices[0].message.content.strip()
        except Exception:
            # Старый SDK (openai<=0.28)
            import openai  # type: ignore
            openai.api_key = api_key
            resp = openai.ChatCompletion.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_text},
                ],
                temperature=0.7,
                max_tokens=400,
            )
            return resp.choices[0].message["content"].strip()
    except Exception as e:
        logger.exception("OpenAI error")
        return f"⚠️ Ошибка OpenAI: {e}"

def on_text(update, context):
    user_text = update.message.text or ""
    reply = _ask_openai(user_text)
    update.message.reply_text(reply)

def main():
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        logger.error("TELEGRAM_BOT_TOKEN не найден в переменных окружения.")
        return

    # v13 синхронный Updater
    updater = Updater(token, use_context=True)
    dp = updater.dispatcher

    # Гарантируем чистый polling (без webhooks и «вторых» экземпляров)
    try:
        updater.bot.delete_webhook(drop_pending_updates=True)
    except Exception:
        pass

    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(MessageHandler(Filters.text & ~Filters.command, on_text))

    updater.start_polling(clean=True)
    updater.idle()

if __name__ == "__main__":
    main()
