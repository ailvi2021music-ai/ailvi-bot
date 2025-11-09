# bot.py
import os
import asyncio
import logging
from typing import List, Tuple

from openai import OpenAI

from psycopg_pool import AsyncConnectionPool

from telegram import Update
from telegram.constants import ParseMode, ALL_UPDATE_TYPES
from telegram.ext import (
    ApplicationBuilder,
    ContextTypes,
    MessageHandler,
    CommandHandler,
    Defaults,        # ВАЖНО: Defaults теперь здесь
    filters,
)

# -------------------- ЛОГИ --------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
log = logging.getLogger("ailvi-bot")

# -------------------- ENV --------------------
TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
OPENAI_API_KEY = os.environ["OPENAI_API_KEY"]
DATABASE_URL = os.environ["DATABASE_URL"]
DB_SSLMODE = os.environ.get("DB_SSLMODE", "require")

MODE = os.environ.get("MODE", "polling").lower()     # "polling" | "webhook"
WEBHOOK_BASE = os.environ.get("WEBHOOK_BASE", "").rstrip("/")
WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET", "ailvi-secret")

ADMIN_CHAT_ID = os.environ.get("ADMIN_CHAT_ID")      # опционально

# -------------------- OPENAI --------------------
client = OpenAI(api_key=OPENAI_API_KEY)

# -------------------- БД --------------------
POOL: AsyncConnectionPool | None = None


def _pg_dsn() -> str:
    if "sslmode=" in DATABASE_URL:
        return DATABASE_URL
    sep = "&" if "?" in DATABASE_URL else "?"
    return f"{DATABASE_URL}{sep}sslmode={DB_SSLMODE}"


async def db_init():
    global POOL
    if POOL is None:
        POOL = AsyncConnectionPool(_pg_dsn(), min_size=1, max_size=5, kwargs={"prepare_threshold": 0})
        log.info("Postgres pool created")

    async with POOL.connection() as con:
        async with con.cursor() as cur:
            await cur.execute(
                """
                create table if not exists users (
                  user_id bigint primary key,
                  created_at timestamptz default now()
                );
                """
            )
            await cur.execute(
                """
                create table if not exists messages (
                  id bigserial primary key,
                  user_id bigint not null,
                  role text not null check (role in ('user','assistant','system')),
                  content text not null,
                  created_at timestamptz default now()
                );
                """
            )
        await con.commit()
    log.info("DB schema ensured")


async def db_add_user(user_id: int):
    async with POOL.connection() as con:
        async with con.cursor() as cur:
            await cur.execute(
                "insert into users(user_id) values (%s) on conflict (user_id) do nothing;",
                (user_id,),
            )
        await con.commit()


async def db_add_message(user_id: int, role: str, content: str):
    async with POOL.connection() as con:
        async with con.cursor() as cur:
            await cur.execute(
                "insert into messages(user_id, role, content) values (%s,%s,%s);",
                (user_id, role, content),
            )
        await con.commit()


async def db_recent_dialogue(user_id: int, limit_pairs: int = 10) -> List[Tuple[str, str]]:
    async with POOL.connection() as con:
        async with con.cursor() as cur:
            await cur.execute(
                """
                select role, content
                from messages
                where user_id=%s and role in ('user','assistant')
                order by created_at desc
                limit %s;
                """,
                (user_id, limit_pairs * 2),
            )
            rows = await cur.fetchall()
    rows.reverse()
    return rows  # [(role, content), ...]


# -------------------- СТИЛЬ --------------------
SYSTEM_PROMPT = (
    "Ты — AILVI, мягкий наставник. Говоришь по-русски тепло и глубоко, без давления, "
    "уважая нормы Ислама. Никогда не упоминай OpenAI/ChatGPT/модель. "
    "Ответы форматируй в HTML (<b>, <i>, <u>, <br>), делай абзацы через пустую строку. "
    "Веди человека маленькими шагами к ясности: сильные стороны, ценности, роли, спокойные действия."
)

WELCOME_TEXT = (
    "<b>Ассаляму Алейкум уа РахматуЛлахи уа Баракятух! 👋🏻</b>\n\n"
    "Добро пожаловать в пространство, где Сердце узнаёт себя заново.\n\n"
    "Давай вместе, спокойно, шаг за шагом, откроем дары, которые Аллах уже вложил "
    "в твою Душу — силы, таланты и намерения. 💎\n\n"
    "Пусть Аллах сделает этот путь лёгким, благословенным и наполненным пониманием!\n\n"
    "Чтобы начать глубокую распаковку — напиши: <b>Начинаем</b>"
)

FIRST_QUESTION = (
    "<b>С радостью начинаю распаковку. ✨</b>\n\n"
    "Начнём с самого важного для тебя сейчас.\n\n"
    "<i>Расскажи кратко:</i> какой большой вопрос у тебя на сердце — про смысл, призвание, "
    "отношения с работой или ощущение себя? Например: «не понимаю, где моя сила», "
    "«хочу ясности в работе», «чувствую усталость и хочу перемен»."
)

# -------------------- АНТИ-РАСКРЫТИЕ --------------------
DENY_PATTERNS = [
    "openai", "chatgpt", "as an ai", "i am an ai", "i'm an ai",
    "as a model", "language model", "gpt", "gpt-4", "gpt-4o",
    "powered by openai", "модель искусственного интеллекта", "как модель", "как чатгпт",
]


def contains_forbidden(text: str) -> bool:
    low = (text or "").lower()
    return any(p in low for p in DENY_PATTERNS)


def rewrite_to_safe(_: str) -> str:
    return (
        "<b>Я — твой мягкий наставник AILVI.</b><br><br>"
        "Давай сосредоточимся на тебе: ценности, сильные стороны, роли и спокойные шаги. "
        "Сформулируй, пожалуйста, ближайший запрос — и я помогу разобрать его по-тёплому. 🌿"
    )


# -------------------- ГЕНЕРАЦИЯ --------------------
async def ai_reply(user_id: int, user_text: str) -> str:
    history = await db_recent_dialogue(user_id, limit_pairs=10)

    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    for role, content in history:
        messages.append({"role": role, "content": content})
    messages.append({"role": "user", "content": user_text})

    def _call():
        return client.chat.completions.create(
            model="gpt-4o-mini",
            messages=messages,
            temperature=0.7,
            max_tokens=800,
        )

    resp = await asyncio.to_thread(_call)
    answer = (resp.choices[0].message.content or "").strip()

    if contains_forbidden(answer):
        answer = rewrite_to_safe(answer)

    return answer


# -------------------- ХЭНДЛЕРЫ --------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    await db_add_user(uid)
    await db_add_message(uid, "system", "START")
    await update.message.reply_text(WELCOME_TEXT)


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return

    uid = update.effective_user.id
    text = (update.message.text or "").strip()
    await db_add_user(uid)

    if text.lower() in ("начинаем", "начать", "поехали"):
        await db_add_message(uid, "user", text)
        await update.message.reply_text(FIRST_QUESTION)
        return

    await db_add_message(uid, "user", text)
    try:
        answer = await ai_reply(uid, text)
    except Exception as e:
        logging.exception("ai_reply failed: %s", e)
        answer = (
            "<b>Небольшая задержка…</b><br><br>"
            "Попробуй сформулировать мысль одной фразой — я рядом. 🌿"
        )
    await db_add_message(uid, "assistant", answer)
    await update.message.reply_text(answer, disable_web_page_preview=True)


# -------------------- APP --------------------
async def on_start(app):
    await db_init()
    if MODE == "webhook":
        if not WEBHOOK_BASE:
            raise RuntimeError("WEBHOOK_BASE is empty while MODE=webhook")
        url = f"{WEBHOOK_BASE}/tg/{WEBHOOK_SECRET}"
        await app.bot.set_webhook(url=url, secret_token=WEBHOOK_SECRET, drop_pending_updates=True)
        logging.info("Webhook set to %s", url)
    else:
        try:
            await app.bot.delete_webhook(drop_pending_updates=True)
        except Exception:
            pass
        logging.info("Webhook deleted; using long polling")


def build_app():
    # ВАЖНО: Defaults берём из telegram.ext.Defaults
    defaults = Defaults(parse_mode=ParseMode.HTML, disable_web_page_preview=True)

    app = (
        ApplicationBuilder()
        .token(TELEGRAM_BOT_TOKEN)
        .concurrent_updates(True)
        .defaults(defaults)
        .http_version("1.1")
        .build()
    )

    app.add_handler(CommandHandler(["start", "help"], start))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))

    app.post_init = on_start
    return app


if __name__ == "__main__":
    application = build_app()

    if MODE == "webhook":
        application.run_webhook(
            listen="0.0.0.0",
            port=int(os.environ.get("PORT", "10000")),
            secret_token=WEBHOOK_SECRET,
            webhook_path=f"/tg/{WEBHOOK_SECRET}",
        )
    else:
        application.run_polling(
            allowed_updates=ALL_UPDATE_TYPES,
            drop_pending_updates=True,
            close_loop=False,
            stop_signals=None,
        )
