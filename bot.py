import os
import asyncio
import logging
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

# === OpenAI SDK ===
# Используем новый клиент. Модель задаётся через переменную окружения MODEL.
try:
    from openai import OpenAI
except Exception as e:
    raise RuntimeError(
        "OpenAI SDK not найден. Убедись, что в requirements.txt есть 'openai>=1.40.0'"
    ) from e


# --------------------------- Конфигурация --------------------------- #

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
MODEL = os.getenv("MODEL", "gpt-4.1-mini")  # можешь сменить на gpt-5-mini, когда будет оплата

FREE_MESSAGE_LIMIT = int(os.getenv("FREE_MESSAGE_LIMIT", "10"))

if not OPENAI_API_KEY:
    raise RuntimeError("Переменная окружения OPENAI_API_KEY не задана")
if not TELEGRAM_BOT_TOKEN:
    raise RuntimeError("Переменная окружения TELEGRAM_BOT_TOKEN не задана")

client = OpenAI(api_key=OPENAI_API_KEY)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)
logger = logging.getLogger("ailvi-bot")


# --------------------------- Память сессий --------------------------- #
# Простая in-memory память (на Render free-инстансе с перезапуском это нормально).
# Для продакшена лучше Redis/DB.
USER_STATE = {}  # {user_id: {"count": int, "history": [ {"role":"user/assistant", "content": "..."} ] }}


# --------------------------- Тексты --------------------------- #

WELCOME_TEXT = (
    "Ассаляму Алейкум уа РахматуЛлахи уа Баракятух! 👋🏻\n\n"
    "Добро пожаловать в пространство, где Сердце узнаёт себя заново.\n\n"
    "Давай вместе, спокойно, шаг за шагом откроем драгоценные дары, которые Аллах уже вложил в твою Душу — "
    "силы, таланты, намерения, которые ждут, когда ты увидишь их Свет. 💎\n\n"
    "Пусть Аллах сделает этот путь лёгким, благословенным и наполненным пониманием!"
)

PAYWALL_TEXT = (
    "Я вижу, что тебе это важно — ты задал(а) уже несколько вопросов. ❤️‍🔥\n\n"
    "Чтобы я продолжал сопровождать тебя глубже и чаще, включи полную версию. "
    "Она откроет безлимитные ответы, сохранение прогресса и персональные мини-эксперименты.\n\n"
    "Если хочешь — напиши «продолжить», и я ещё дам 1–2 ответа, а затем подскажу, как оформить подписку."
)


# --------------------------- Хелперы --------------------------- #

def get_user_state(user_id: int):
    if user_id not in USER_STATE:
        USER_STATE[user_id] = {"count": 0, "history": []}
    return USER_STATE[user_id]


async def openai_answer(history):
    """
    history — список сообщений формата:
      [{"role":"system"|"user"|"assistant", "content":"..."}]
    Возвращает str — ответ ассистента.
    """
    # Безопасный системный промпт в духе AILVI
    system_prompt = (
        "Ты — AILVI: мягкий, ясный духовный проводник. Помогаешь человеку распаковать сильные стороны, "
        "ценности и сделать маленькие осмысленные шаги. Избегай коуч-клише и пустых обещаний. "
        "Говори коротко и по делу, тепло и уважительно. Если человек говорит об Исламе — "
        "поддерживай уважительно, без фетв и категоричных суждений."
    )

    # Собираем историю: системное сообщение + последние реплики пользователя/ассистента
    messages = [{"role": "system", "content": system_prompt}]
    messages.extend(history[-10:])  # последние 10 – достаточно для контекста на старте

    try:
        # Chat Completions
        resp = client.chat.completions.create(
            model=MODEL,
            messages=messages,
            temperature=0.6,
            max_tokens=600,  # ограничим разумно
        )
        return resp.choices[0].message.content.strip()
    except Exception as e:
        # Специальная обработка квоты
        msg = str(e)
        if "insufficient_quota" in msg or "You exceeded your current quota" in msg:
            logger.error("OpenAI quota error: %s", msg)
            return (
                "Похоже, исчерпан лимит на ответы ИИ. Я скоро вернусь. "
                "Если нужно срочно — напиши одно короткое уточнение, постараюсь ответить максимально кратко."
            )
        logger.exception("OpenAI error")
        return "Сейчас у меня техническая заминка. Давай попробуем ещё раз через минуту."


# --------------------------- Handlers --------------------------- #

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    USER_STATE[user_id] = {"count": 0, "history": []}  # жёсткий сброс
    await update.message.reply_text(WELCOME_TEXT)


async def reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    USER_STATE[user_id] = {"count": 0, "history": []}
    await update.message.reply_text("Сессию очистил. Напиши, с чего начнём.")
    await update.message.reply_text(WELCOME_TEXT)


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return

    user_id = update.effective_user.id
    text = update.message.text.strip()
    state = get_user_state(user_id)

    # учтём /start как обычный текст – тут ничего не делаем, им занимается start()
    if text.startswith("/"):
        return

    # Инкремент считаем только за содержательные сообщения
    state["count"] += 1
    # Пишем в историю
    state["history"].append({"role": "user", "content": text})

    # Порог бесплатных сообщений
    if state["count"] > FREE_MESSAGE_LIMIT:
        # Дадим мягкое сообщение-приглашение
        await update.message.reply_text(PAYWALL_TEXT)
        # Разрешим ещё 1-2 ответа «поверх порога», но сейчас просто останавливаемся
        return

    # Основной ответ OpenAI
    answer = await openai_answer(state["history"])
    # Пишем ответ в историю
    state["history"].append({"role": "assistant", "content": answer})
    await update.message.reply_text(answer)


# --------------------------- Health-check HTTP --------------------------- #
# Render любит, когда что-то слушает порт (health checks). Лёгкий HTTP-сервер.

class _HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write(b"OK")

def start_health_server():
    port = int(os.getenv("PORT", "10000"))
    server = HTTPServer(("0.0.0.0", port), _HealthHandler)
    logger.info(f"Health server on port {port}")
    server.serve_forever()


# --------------------------- Запуск --------------------------- #

def run_telegram_bot():
    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("reset", reset))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))

    # В PTB v21 run_polling() — coroutine, его нужно запускать через asyncio.run
    asyncio.run(app.run_polling(
        allowed_updates=Update.ALL_TYPES  # безопасно
    ))

if __name__ == "__main__":
    # 1) Фоновый health-сервер
    threading.Thread(target=start_health_server, daemon=True).start()

    # 2) Телеграм-бот (polling)
    run_telegram_bot()
