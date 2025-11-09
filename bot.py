# bot.py
import os
import html
import logging
import asyncio
from datetime import datetime, timezone

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import (
    Application, CommandHandler, MessageHandler, ContextTypes, filters
)

# -------------------- Настройка логов --------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s"
)
log = logging.getLogger("ailvi-bot")

# -------------------- ENV --------------------
TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
OPENAI_API_KEY     = os.environ.get("OPENAI_API_KEY", "")
DATABASE_URL       = os.environ.get("DATABASE_URL", "")
ADMIN_CHAT_ID      = os.environ.get("ADMIN_CHAT_ID")  # опционально для алертов
DB_SSLMODE         = os.environ.get("DB_SSLMODE", "require")

# -------------------- PostgreSQL (минимум) --------------------
# Лёгкий слой: одна таблица сообщений, одна — статусы.
POOL = None
try:
    import psycopg
    from psycopg_pool import ConnectionPool
    if DATABASE_URL:
        # Добавим sslmode в строку, если его нет
        conn_str = DATABASE_URL if "sslmode=" in DATABASE_URL else (
            DATABASE_URL + (("&" if "?" in DATABASE_URL else "?") + f"sslmode={DB_SSLMODE}")
        )
        POOL = ConnectionPool(conn_str, min_size=1, max_size=5, kwargs={"connect_timeout": 10})
        with POOL.connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                create table if not exists dialog_messages(
                    id bigserial primary key,
                    user_id bigint not null,
                    role text not null,           -- 'user' | 'bot'
                    text text not null,
                    ts   timestamptz not null default now()
                );
                """)
                cur.execute("""
                create table if not exists user_state(
                    user_id bigint primary key,
                    stage text not null default 'intro',
                    updated_at timestamptz not null default now()
                );
                """)
            conn.commit()
        log.info("DB: connected & migrations OK")
    else:
        log.warning("DB: DATABASE_URL not set — сохранение диалога отключено")
except Exception as e:
    log.exception("DB init error: %s", e)

async def db_write_message(user_id: int, role: str, text: str):
    if not POOL: 
        return
    try:
        async with POOL.connection() as aconn:
            async with aconn.cursor() as cur:
                await cur.execute(
                    "insert into dialog_messages(user_id, role, text, ts) values (%s,%s,%s, %s)",
                    (user_id, role, text, datetime.now(timezone.utc))
                )
                await cur.execute(
                    """
                    insert into user_state(user_id, stage, updated_at)
                    values (%s, %s, now())
                    on conflict (user_id) do update set updated_at=excluded.updated_at
                    """,
                    (user_id, "active")
                )
            await aconn.commit()
    except Exception as e:
        log.exception("DB write failed: %s", e)

# -------------------- Текст и форматирование --------------------
WELCOME_TEXT = (
    "<b>Ассаляму Алейкум уа РахматуЛлахи уа Баракятух! 👋🏻</b>\n\n"
    "Добро пожаловать в пространство, где Сердце узнаёт себя заново.\n\n"
    "Давай вместе, спокойно, шаг за шагом, откроем дары, которые Аллах уже вложил "
    "в твою душу — силы, таланты, намерения, которые ждут, когда ты увидишь их свет. 💎\n\n"
    "Пусть Аллах сделает этот путь лёгким, благословенным и наполненным пониманием!\n\n"
    "Чтобы начать глубокую распаковку — напиши: <b>Начинаем</b>."
)

INTRO_PROMPT = (
    "<b>С радостью начинаю распаковку. ✨</b>\n\n"
    "Расскажи коротко, <i>что сейчас важнее всего</i> внутри: про смысл, призвание, отношения с работой "
    "или ощущение себя. Примеры: «не понимаю, где моя сила», «хочу ясности в работе», «усталость и хочу перемен».\n\n"
    "Можешь в двух-трёх предложениях. 🌿"
)

# Вопросы первого шага — мягко и без гендерных обращений
QUESTIONS_BLOCK_1 = (
    "<b>Понимаю, это важный вопрос.</b> Чтобы нащупать направление, давай начнём с простого:\n\n"
    "1) <b>Что приносит радость?</b> Вспомни, что делает тебя живым(ой). Были ли увлечения, любимые занятия?\n\n"
    "2) <b>Что вызывает устойчивый интерес?</b> Темы, к которым возвращаешься, то, что хотелось бы пробовать.\n\n"
    "3) <b>Как хочешь приносить пользу?</b> В чём естественно получается быть полезным(ой) другим?\n\n"
    "Ответь свободно — как идёт. Я рядом и буду бережно направлять. 🌱"
)

# -------------------- Анти-раскрытие происхождения --------------------
OPENAI_TRIGGERS = (
    "openai", "chatgpt", "gpt", "опенай", "чатгпт", "чья ты модель", "какая ты модель",
    "кто ты по технологии", "api ключ", "какой движок"
)

ANTI_DISCLOSURE_REPLY = (
    "Я духовный помощник AILVI, созданный, чтобы мягко вести диалог о смысле, талантах и пути. "
    "Технические детали платформы не относятся к задаче распаковки, поэтому держу фокус на тебе и твоём движении. 🌿"
)

# -------------------- Хелперы --------------------
def looks_like_anti_disclosure(text: str) -> bool:
    t = text.lower()
    return any(k in t for k in OPENAI_TRIGGERS)

def needs_start_flow(text: str) -> bool:
    return text.strip().lower() in ("начинаем", "начать", "старт", "/go")

async def safe_send(chat_id: int, text: str, ctx: ContextTypes.DEFAULT_TYPE):
    try:
        await ctx.bot.send_message(chat_id, text, parse_mode=ParseMode.HTML, disable_web_page_preview=True)
    except Exception as e:
        log.exception("Send error: %s", e)

async def alert_admin(msg: str, ctx: ContextTypes.DEFAULT_TYPE):
    if ADMIN_CHAT_ID:
        try:
            await ctx.bot.send_message(int(ADMIN_CHAT_ID), f"⚠️ {html.escape(msg)}")
        except Exception:
            pass

# -------------------- Хэндлеры --------------------
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    await db_write_message(uid, "bot", WELCOME_TEXT)
    await update.message.reply_text(WELCOME_TEXT, parse_mode=ParseMode.HTML, disable_web_page_preview=True)

async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return
    uid = update.effective_user.id
    text = update.message.text or ""

    # Анти-раскрытие
    if looks_like_anti_disclosure(text):
        await db_write_message(uid, "user", text)
        await db_write_message(uid, "bot", ANTI_DISCLOSURE_REPLY)
        await update.message.reply_text(ANTI_DISCLOSURE_REPLY, parse_mode=ParseMode.HTML)
        return

    # Старт «Распаковки»
    if needs_start_flow(text):
        await db_write_message(uid, "user", text)
        await db_write_message(uid, "bot", INTRO_PROMPT)
        await update.message.reply_text(INTRO_PROMPT, parse_mode=ParseMode.HTML)
        # Следующим сообщением — первый блок вопросов
        await asyncio.sleep(0.3)
        await db_write_message(uid, "bot", QUESTIONS_BLOCK_1)
        await update.message.reply_text(QUESTIONS_BLOCK_1, parse_mode=ParseMode.HTML)
        return

    # Обычный диалог: сохраняем и продвигаем мягко
    await db_write_message(uid, "user", text)

    # Лёгкая логика уточнений, если человек ответил «не знаю»/«сложно»
    low = text.strip().lower()
    if any(k in low for k in ("не знаю", "сложно", "пока не понимаю", "затрудняюсь")):
        reply = (
            "<b>Это нормально не знать сразу. 🌿</b>\n\n"
            "Давай зайдём проще: вспомни два момента из жизни, когда стало <i>ясно и спокойно</i>. "
            "Где ты был(а)? Что делал(а)? С кем? Что именно придало ощущение правильности?\n\n"
            "Опиши хотя бы один эпизод — коротко."
        )
        await db_write_message(uid, "bot", reply)
        await update.message.reply_text(reply, parse_mode=ParseMode.HTML)
        return

    # Базовый мягкий ответ-продвижение
    reply = (
        "<b>Слышу тебя.</b> Давай закрепим двумя шагами:\n\n"
        "• Запиши 1–2 занятия, после которых обычно появляется лёгкость или энергия (даже если они кажутся «мелочами»).\n"
        "• Назови одну небольшую пользу, которую ты уже умеешь давать людям (подсказка: чем к тебе обращаются знакомые?).\n\n"
        "Готов принять твой ответ. ✍️"
    )
    await db_write_message(uid, "bot", reply)
    await update.message.reply_text(reply, parse_mode=ParseMode.HTML)

async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "<b>Как со мной работать</b>\n\n"
        "• Напиши <b>Начинаем</b>, чтобы запустить распаковку.\n"
        "• Отвечай свободно и коротко — я буду бережно направлять.\n"
        "• В любой момент можно написать «стоп» или «пауза» — и мы замрём.\n"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    log.exception("Exception in handler: %s", context.error)
    await alert_admin(f"Exception: {context.error}", context)

# -------------------- Запуск --------------------
def start_bot():
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))

    app.add_error_handler(error_handler)

    # Важно: никакого ALL_UPDATE_TYPES — используем Update.ALL_TYPES
    app.run_polling(
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=True,
        close_loop=False,
        stop_signals=None,
    )

if __name__ == "__main__":
    start_bot()
