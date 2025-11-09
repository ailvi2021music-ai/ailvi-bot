import os
import json
import asyncio
import logging
import threading
from datetime import datetime

from flask import Flask, request, abort

from telegram import Update, Bot
from telegram.constants import ParseMode
from telegram.error import TelegramError
from telegram.ext import (
    Application, ApplicationBuilder, CommandHandler, MessageHandler,
    filters, ContextTypes
)

# -------------------- ЛОГИ --------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s"
)
log = logging.getLogger("ailvi-bot")

# -------------------- ENV --------------------
TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
DATABASE_URL = os.environ.get("DATABASE_URL", "")
DB_SSLMODE = os.environ.get("DB_SSLMODE", "require")
MODE = os.environ.get("MODE", "polling").lower()            # polling | webhook
WEBHOOK_BASE = os.environ.get("WEBHOOK_BASE", "")           # https://<service>.onrender.com
WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET", "secret")
PORT = int(os.environ.get("PORT", "10000"))

ADMIN_CHAT_ID = os.environ.get("ADMIN_CHAT_ID", "")
ALERTS_ENABLED = os.environ.get("ALERTS_ENABLED", "true").lower() == "true"

# -------------------- ALERTS --------------------
async def alert(ctx: ContextTypes.DEFAULT_TYPE, text: str):
    if not ALERTS_ENABLED or not ADMIN_CHAT_ID:
        return
    try:
        await ctx.bot.send_message(chat_id=int(ADMIN_CHAT_ID), text=f"⚠️ {text}")
    except Exception as e:
        log.error("alert send failed: %s", e)

# -------------------- FLASK --------------------
app = Flask(__name__)

@app.get("/")
def health_root():
    return "OK", 200

@app.get("/health")
def health():
    # можно расширить: пинг до БД и т.д.
    return json.dumps({"status": "ok", "time": datetime.utcnow().isoformat()}), 200, {"Content-Type": "application/json"}

# -------------------- PTB APPLICATION --------------------
application: Application = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()
bot: Bot = application.bot

WELCOME_TEXT = (
    "Ассаламу алейкум! ✨\n\n"
    "Запускаю распаковку. Пиши коротко и по-делу — я буду вести бережно и глубоко.\n\n"
    "Чтобы начать — напиши: *Начинаем*"
)

# --------- ГЛОБАЛЬНАЯ ОБРАБОТКА ОШИБОК ---------
async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    log.exception("Handler error", exc_info=context.error)
    await alert(context, f"Ошибка в обработчике: {context.error!r}")

application.add_error_handler(on_error)

# --------- ХЕЛПЕРЫ ФОРМАТА ---------
def md(text: str) -> str:
    # Телеграм будет понимать MarkdownV2/HTML. Здесь используем HTML — меньше экранирования.
    return text

# --------- ХЕНДЛЕРЫ ---------
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_chat.send_message(WELCOME_TEXT, parse_mode=ParseMode.MARKDOWN)

async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (update.message.text or "").strip()

    if text.lower() == "начинаем":
        reply = (
            "<b>С радостью начинаю распаковку.</b> ✨\n\n"
            "Скажи мне, какая тема у тебя сейчас на первом плане?\n"
            "• работа/доход 💼\n"
            "• призвание/смысл 🌱\n"
            "• энергия/усталость 🔋\n"
            "• отношения с делом/людьми 🤝\n\n"
            "Напиши одним словом или короткой фразой."
        )
        await update.message.reply_html(reply)
        return

    # Это простая демонстрация шага 1: уточнение фокуса
    reply = (
        "<b>Понял.</b> Двигаемся бережно.\n\n"
        "1) <b>Что приносит радость?</b>\n"
        "Вспомни моменты/занятия, после которых внутри было светло. 1–3 примера.\n\n"
        "2) <b>Что тянет/интересует?</b>\n"
        "Темы, к которым возвращаешься, даже когда никто не просит.\n\n"
        "3) <b>Как хочешь помогать?</b>\n"
        "Кому и чем тебе естественно быть полезным?\n\n"
        "Ответь коротко, пунктами. Я дальше соберу структуру."
    )
    await update.message.reply_html(reply)

application.add_handler(CommandHandler("start", start_command))
application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler))

# -------------------- WEBHOOK РОУТ --------------------
# При MODE=webhook сюда будет постучаться Telegram
@app.post("/telegram/<token>")
def telegram_webhook(token: str):
    if token != TELEGRAM_BOT_TOKEN:
        abort(403)
    secret = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
    if secret != WEBHOOK_SECRET:
        abort(403)

    try:
        data = request.get_json(force=True)
    except Exception:
        abort(400)

    update = Update.de_json(data, bot)
    # Запускаем асинхронную обработку
    try:
        asyncio.get_event_loop().create_task(application.process_update(update))
    except RuntimeError:
        # если ещё нет лупа (редко), запускаем в фоне
        threading.Thread(target=lambda: asyncio.run(application.process_update(update)), daemon=True).start()
    return "OK", 200

# -------------------- СЛУЖЕБНЫЕ ФУНКЦИИ --------------------
async def setup_webhook(ctx: ContextTypes.DEFAULT_TYPE):
    url = f"{WEBHOOK_BASE}/telegram/{TELEGRAM_BOT_TOKEN}"
    try:
        await ctx.bot.set_webhook(
            url=url,
            secret_token=WEBHOOK_SECRET,
            drop_pending_updates=True,
        )
        if ALERTS_ENABLED:
            await ctx.bot.send_message(int(ADMIN_CHAT_ID), f"🛰️ Вебхук установлен:\n{url}")
        log.info("Webhook set to %s", url)
    except TelegramError as e:
        log.error("set_webhook failed: %s", e)
        raise

async def delete_webhook(ctx: ContextTypes.DEFAULT_TYPE):
    try:
        await ctx.bot.delete_webhook(drop_pending_updates=True)
        log.info("Webhook deleted")
        if ALERTS_ENABLED and ADMIN_CHAT_ID:
            await ctx.bot.send_message(int(ADMIN_CHAT_ID), "🧹 Вебхук удалён (режим polling)")
    except TelegramError as e:
        log.error("delete_webhook failed: %s", e)

def run_polling_in_background():
    async def runner():
        # На polling режиме гарантированно удалим вебхук
        await delete_webhook(application)
        if ALERTS_ENABLED and ADMIN_CHAT_ID:
            try:
                await bot.send_message(int(ADMIN_CHAT_ID), "🚴 Запуск бота в режиме polling")
            except Exception:  # не критично
                pass
        await application.initialize()
        await application.start()
        await application.updater.start_polling(allowed_updates=Update.ALL_TYPES)
        # updater.start_polling блокирует — держим его
        await application.updater.wait()
    asyncio.run(runner())

# -------------------- MAIN --------------------
if __name__ == "__main__":
    if MODE == "webhook":
        # установим вебхук при старте (в фоне, после init)
        async def init_and_set():
            await application.initialize()
            await application.start()
            await setup_webhook(application)
            if ALERTS_ENABLED and ADMIN_CHAT_ID:
                try:
                    await bot.send_message(int(ADMIN_CHAT_ID), "🛰️ Запуск бота в режиме webhook")
                except Exception:
                    pass
        threading.Thread(target=lambda: asyncio.run(init_and_set()), daemon=True).start()

        # Запускаем Flask, чтобы Render видел порт
        app.run(host="0.0.0.0", port=PORT)

    else:  # polling
        # Запускаем polling в отдельном потоке,
        # а Flask оставляем для health/порта, чтобы Render не ругался
        threading.Thread(target=run_polling_in_background, daemon=True).start()
        app.run(host="0.0.0.0", port=PORT)
