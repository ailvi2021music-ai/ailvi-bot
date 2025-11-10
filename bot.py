# bot.py
# -*- coding: utf-8 -*-

import os
import asyncio
import logging
from datetime import datetime, timezone

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    Defaults,
    filters,
)

# ---- DB (опционально) -------------------------------------------------------
DB_POOL = None
USE_DB = False

try:
    import psycopg  # psycopg3
    from psycopg_pool import ConnectionPool
except Exception:  # БД не обязательна для работы бота
    psycopg = None
    ConnectionPool = None

# ---- Логирование -------------------------------------------------------------
logging.basicConfig(
    format="%(asctime)s %(levelname)s %(name)s | %(message)s",
    level=logging.INFO,
)
log = logging.getLogger("ailvi-bot")


# ---- Вспомогательные функции -------------------------------------------------
def env(name: str, default: str | None = None) -> str | None:
    v = os.getenv(name)
    return v if (v is not None and v != "") else default


async def db_init():
    """Создаём пул и таблицу логов, если есть DATABASE_URL."""
    global DB_POOL, USE_DB
    dsn = env("DATABASE_URL")
    if not dsn or not psycopg or not ConnectionPool:
        log.info("DB: off (DATABASE_URL missing or psycopg not installed)")
        USE_DB = False
        return

    DB_POOL = ConnectionPool(conninfo=dsn, max_size=4, kwargs={"autocommit": True})
    USE_DB = True
    log.info("DB: pool created")

    create_sql = """
    CREATE TABLE IF NOT EXISTS bot_logs (
        id BIGSERIAL PRIMARY KEY,
        chat_id BIGINT,
        username TEXT,
        direction TEXT,        -- 'in' | 'out'
        text TEXT,
        ts TIMESTAMPTZ DEFAULT now()
    );
    """
    try:
        with DB_POOL.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(create_sql)
        log.info("DB: table bot_logs ready")
    except Exception as e:
        log.exception("DB init failed: %s", e)
        USE_DB = False  # не ломаем бота, просто отключаем запись


async def db_write(chat_id: int, username: str | None, direction: str, text: str):
    if not USE_DB or DB_POOL is None:
        return
    try:
        with DB_POOL.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO bot_logs (chat_id, username, direction, text, ts) VALUES (%s,%s,%s,%s,%s)",
                    (chat_id, username, direction, text, datetime.now(timezone.utc)),
                )
    except Exception as e:
        log.warning("DB write failed: %s", e)


# ---- Ответы ------------------------------------------------------------------
START_TEXT = (
    "<b>Ассаляму алейкум!</b>\n\n"
    "Рад быть рядом и аккуратно помочь разобрать мысли. Я мягко веду диалог, без спешки и оценок. "
    "Если хочешь начать глубокую распаковку — напиши: <b>Начинаем ✨</b>\n\n"
    "Полезные команды:\n"
    "• <code>/health</code> — проверка, что бот жив\n"
    "• Можно просто писать сообщения обычным текстом"
)

WARM_ENTRY = (
    "<b>Начнём с самого важного для тебя сейчас. ✨</b>\n\n"
    "Скажи коротко, какая область зовёт сильнее всего сегодня:\n"
    "— смысл/призвание,\n"
    "— внутреннее состояние,\n"
    "— отношения с работой/делом,\n"
    "— ясность в шагах.\n\n"
    "Напиши одним словом или фразой (например: «призвание», «ясность в шагах»)."
)

FOLLOWUP_HINT = (
    "Принял. Пиши в свободной форме — я уточню и помогу структурировать. "
    "Если захочешь заново — напиши: <b>Начинаем</b>."
)


# ---- Хендлеры ----------------------------------------------------------------
async def cmd_health(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("OK")
    await db_write(update.effective_chat.id, update.effective_user.username, "out", "OK")


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await db_write(update.effective_chat.id, update.effective_user.username, "in", "/start")
    await update.message.reply_text(START_TEXT, parse_mode=ParseMode.HTML)
    await db_write(update.effective_chat.id, update.effective_user.username, "out", START_TEXT)


async def on_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return

    text = update.message.text.strip()
    await db_write(update.effective_chat.id, update.effective_user.username, "in", text)

    # Ключевая точка входа курса
    if text.lower().startswith("начинаем"):
        await update.message.reply_text(WARM_ENTRY, parse_mode=ParseMode.HTML)
        await db_write(update.effective_chat.id, update.effective_user.username, "out", WARM_ENTRY)
        return

    # Мягкий ответ по умолчанию
    reply = (
        "<i>Я услышал.</i> Расскажи, пожалуйста, на что это похоже изнутри — мысль, чувство или ситуация? "
        "Пару фактов и то, что хотелось бы изменить. "
        "Если нужно начать сначала — напиши: <b>Начинаем</b>."
    )
    await update.message.reply_text(reply, parse_mode=ParseMode.HTML)
    await db_write(update.effective_chat.id, update.effective_user.username, "out", reply)


# ---- Запуск ------------------------------------------------------------------
async def main():
    token = env("TELEGRAM_BOT_TOKEN")
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is not set")

    # HTML форматирование по умолчанию
    defaults = Defaults(parse_mode=ParseMode.HTML)

    application: Application = (
        ApplicationBuilder()
        .token(token)
        .defaults(defaults)
        .build()
    )

    # Команды
    application.add_handler(CommandHandler("health", cmd_health))
    application.add_handler(CommandHandler("start", cmd_start))
    # Сообщения
    application.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), on_message))

    # Инициализация БД (если есть)
    await db_init()

    # Режим по умолчанию — polling (на Render это надёжно и бесплатно)
    mode = (env("MODE", "polling") or "polling").lower()
    if mode == "webhook":
        # Webhook поддерживаем лишь на случай, если ты когда-нибудь решишь вернуться к нему.
        base = env("WEBHOOK_BASE")
        secret = env("WEBHOOK_SECRET", "secret")
        port = int(env("PORT", "10000"))
        if not base:
            raise RuntimeError("WEBHOOK_BASE is required for webhook mode")
        url = f"{base.rstrip('/')}/bot{secret}"
        log.info("Starting webhook at %s", url)
        await application.bot.set_webhook(url=url, secret_token=secret)
        await application.run_webhook(
            listen="0.0.0.0",
            port=port,
            url_path=f"bot{secret}",
            secret_token=secret,
            stop_signals=None,
        )
    else:
        log.info("Starting polling…")
        # В v21 не указываем устаревший constants.ALL_UPDATE_TYPES
        await application.run_polling(poll_interval=1.6)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        pass
