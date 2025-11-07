import os
import logging
import threading
from flask import Flask
from openai import OpenAI

from telegram import (
    Update,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    BotCommand,
)
from telegram.ext import (
    ApplicationBuilder,
    ContextTypes,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
)

# -----------------------------
# Конфигурация и клиенты
# -----------------------------
logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("ailvi-bot")

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

if not OPENAI_API_KEY or not TELEGRAM_BOT_TOKEN:
    raise RuntimeError("Нужно задать переменные окружения OPENAI_API_KEY и TELEGRAM_BOT_TOKEN")

client = OpenAI(api_key=OPENAI_API_KEY)


# -----------------------------
# Текст приветствия
# -----------------------------
GREETING = (
    "Ассаляму Алейкум уа РахматуЛлахи уа Баракятух! 👋🏻\n\n"
    "Добро пожаловать в пространство, где Сердце узнаёт себя заново.\n\n"
    "Давай вместе, спокойно, шаг за шагом откроем драгоценные дары, которые Аллах уже вложил в твою Душу — "
    "силы, таланты, намерения, которые ждут, когда ты увидишь их Свет. 💎\n\n"
    "Пусть Аллах сделает этот путь лёгким, благословенным и наполненным пониманием! 🚀"
)

SYSTEM_PROMPT = (
    "Ты — AILVI: мягкий, бережный проводник. "
    "Помогаешь человеку распаковать сильные стороны, ценности и естественные роли, "
    "поддерживая верой, спокойной ясностью и конкретными микрошагами. "
    "Пиши кратко, чётко, человечно. Уважай Ислам: избегай всего харам, поощряй искреннее обращение к Аллаху. "
    "Когда уместно — задавай один простой вопрос, чтобы помочь человеку увидеть себя яснее."
)

# -----------------------------
# Хэндлеры
# -----------------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Приветствие с кнопкой «Начать»."""
    keyboard = InlineKeyboardMarkup(
        [[InlineKeyboardButton("🚀 Начать", callback_data="start_flow")]]
    )
    if update.message:
        await update.message.reply_text(GREETING, reply_markup=keyboard)
    elif update.callback_query:
        await update.callback_query.message.reply_text(GREETING, reply_markup=keyboard)


async def handle_start_flow(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Нажатие на кнопку «Начать»: убираем клавиши и даём первый вопрос."""
    query = update.callback_query
    await query.answer()
    # убираем кнопки под приветствием
    try:
        await query.edit_message_reply_markup(None)
    except Exception:
        pass

    first_q = (
        "Начинаем. Расскажи, пожалуйста, о 1–2 моментах в твоей жизни, когда ты чувствовал(а) наибольшую живость и смысл: "
        "что это было, что ты делал(а), с кем, почему это наполнило тебя?"
    )
    await query.message.reply_text(first_q)


async def reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Простой «сброс» — фактически просто ещё раз показываем приветствие с кнопкой."""
    await start(update, context)


async def reply_with_openai(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Основной ответ через OpenAI на любое обычное сообщение."""
    if not update.message or not update.message.text:
        return

    user_text = update.message.text.strip()
    try:
        # компактная, быстрая и недорогая модель
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_text},
            ],
            temperature=0.6,
        )
        answer = response.choices[0].message.content or "..."
        await update.message.reply_text(answer)
    except Exception as e:
        logger.exception("OpenAI error")
        await update.message.reply_text(
            "Извини, сейчас не получается ответить. Попробуй ещё раз чуть позже."
        )


async def post_init(app):
    """Удаляем webHook (на всякий случай) и ставим команды меню."""
    try:
        await app.bot.delete_webhook(drop_pending_updates=False)
    except Exception:
        pass

    await app.bot.set_my_commands(
        [
            BotCommand("start", "Показать приветствие"),
            BotCommand("reset", "Перезапустить приветствие"),
        ]
    )


# -----------------------------
# Health-check для Render
# -----------------------------
flask_app = Flask(__name__)

@flask_app.get("/")
def health():
    return "OK", 200

def run_health_server():
    port = int(os.getenv("PORT", "10000"))  # Render обычно ждёт порт из $PORT
    flask_app.run(host="0.0.0.0", port=port)


# -----------------------------
# Точка входа
# -----------------------------
def main():
    # поднимаем health-сервер в отдельном потоке
    threading.Thread(target=run_health_server, daemon=True).start()

    application = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()
    application.post_init = post_init

    # хэндлеры
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("reset", reset))
    application.add_handler(CallbackQueryHandler(handle_start_flow, pattern="^start_flow$"))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, reply_with_openai))

    # запуск polling
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
