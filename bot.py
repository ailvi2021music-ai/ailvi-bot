# bot.py
import asyncio
import logging
import os
from datetime import datetime, timezone
from typing import List, Tuple

import httpx
from openai import OpenAI
from telegram import Update, constants
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

import psycopg
from psycopg.rows import tuple_row
from psycopg_pool import AsyncConnectionPool

# ---------- Конфиг ----------
TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
OPENAI_API_KEY = os.environ["OPENAI_API_KEY"]
DATABASE_URL = os.environ["DATABASE_URL"]  # полный URL из Render
DB_SSLMODE = os.getenv("DB_SSLMODE", "require")  # обычно 'require'

# режим работы чата
WELCOME_TEXT = (
    "Ассаляму Алейкум уа РахматуЛлахи уа Баракятух! 👋🏻<br><br>"
    "Добро пожаловать в пространство, где Сердце узнаёт себя заново.<br><br>"
    "Давай вместе, спокойно, шаг за шагом, откроем дары, которые Аллах уже вложил в твою душу — "
    "силы, таланты, намерения. 💎<br><br>"
    "Пусть Аллах сделает этот путь лёгким и наполненным пониманием!<br><br>"
    "Чтобы начать глубокую распаковку — напиши: <b>Начинаем</b>."
)

SYSTEM_PROMPT = (
    "Ты — мягкий духовный наставник AILVI. Отвечай по-человечески: тепло, кратко, по делу, "
    "без канцелярита. Вежливо избегай любых упоминаний моделей, компаний и технологий. "
    "Никогда не признавайся, что ты ИИ, модель или как-то связан с OpenAI/ChatGPT.\n\n"
    "Контекст: стиль Ислама, мягкость, без осуждения; ты задаёшь наводящие вопросы и ведёшь человека "
    "к ясности: ценности, сильные стороны, где энергия, какие шаги малыми итерациями.\n\n"
    "Форматируй ответ HTML-тегами: <b>жирный</b>, <i>курсив</i>, абзацы через <br><br>. "
    "Эмодзи допустимы умеренно. Не используй Markdown-звёздочки.\n\n"
    "Если человек начинает про работу/деньги раньше времени, мягко возвращай к внутренней ясности "
    "и наблюдениям, обещая вернуться к заработку позже. Не давай списков профессий раньше времени."
)

FIRST_QUESTION = (
    "<b>С радостью начинаю распаковку.</b> ✨<br><br>"
    "Расскажи, какой большой вопрос у тебя сейчас на сердце: про смысл, призвание, отношения с работой "
    "или ощущение себя? Можно коротко: «не понимаю, где моя сила», «хочу ясности в работе», "
    "«чувствую усталость и хочу перемен». 🌿"
)

# ---------- Логирование ----------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s | %(message)s",
)
log = logging.getLogger("ailvi-bot")

# ---------- OpenAI ----------
client = OpenAI(api_key=OPENAI_API_KEY)
httpx_client = httpx.AsyncClient(timeout=60)

# ---------- БД (PostgreSQL, async pool) ----------
POOL: AsyncConnectionPool | None = None


async def db_init() -> None:
    """Создаём соединения и таблицы, если их нет."""
    global POOL
    # добавляем sslmode в DSN, если его нет
    dsn = DATABASE_URL
    if "sslmode=" not in dsn:
        dsn += f"?sslmode={DB_SSLMODE}"

    POOL = AsyncConnectionPool(
        conninfo=dsn,
        max_size=8,
        kwargs={"row_factory": tuple_row},
    )

    async with POOL.connection() as aconn:
        async with aconn.cursor() as cur:
            await cur.execute(
                """
                create table if not exists users (
                    user_id      bigint primary key,
                    created_at   timestamptz not null default now(),
                    state        jsonb not null default '{}'::jsonb
                );
                """
            )
            await cur.execute(
                """
                create table if not exists dialog (
                    id           bigserial primary key,
                    user_id      bigint not null,
                    ts           timestamptz not null default now(),
                    role         text not null,          -- 'user' | 'assistant' | 'system'
                    content      text not null
                );
                """
            )
        await aconn.commit()


async def db_upsert_user(user_id: int) -> None:
    async with POOL.connection() as aconn:
        async with aconn.cursor() as cur:
            await cur.execute(
                """
                insert into users (user_id) values (%s)
                on conflict (user_id) do nothing;
                """,
                (user_id,),
            )
        await aconn.commit()


async def db_add_message(user_id: int, role: str, content: str) -> None:
    async with POOL.connection() as aconn:
        async with aconn.cursor() as cur:
            await cur.execute(
                "insert into dialog (user_id, role, content) values (%s, %s, %s);",
                (user_id, role, content),
            )
        await aconn.commit()


async def db_last_messages(user_id: int, limit: int = 40) -> List[Tuple[str, str]]:
    """Возвращает последние сообщения (role, content)."""
    async with POOL.connection() as aconn:
        async with aconn.cursor() as cur:
            await cur.execute(
                """
                select role, content
                from dialog
                where user_id = %s
                order by id desc
                limit %s;
                """,
                (user_id, limit),
            )
            rows = await cur.fetchall()
    rows.reverse()
    return rows


# ---------- Утилиты ----------
async def send_html(update: Update, text: str) -> None:
    await update.effective_chat.send_message(
        text,
        parse_mode=constants.ParseMode.HTML,
        disable_web_page_preview=True,
    )


def split_for_telegram(text: str, chunk: int = 3800) -> List[str]:
    """Режет длинный HTML-текст на части поменьше."""
    parts: List[str] = []
    s = text
    while len(s) > chunk:
        cut = s.rfind("<br>", 0, chunk)
        if cut < 0:
            cut = chunk
        parts.append(s[:cut])
        s = s[cut:]
    if s:
        parts.append(s)
    return parts


async def ai_reply(user_id: int, user_text: str) -> str:
    """Генерируем ответ с учётом последних сообщений пользователя."""
    # сохраняем пользовательское сообщение
    await db_add_message(user_id, "user", user_text)

    history = await db_last_messages(user_id, limit=40)
    # формируем messages для чата
    msgs = [{"role": "system", "content": SYSTEM_PROMPT}]
    for role, content in history:
        if role in {"user", "assistant"}:
            msgs.append({"role": role, "content": content})

    # запрос к OpenAI
    resp = await asyncio.to_thread(
        client.chat.completions.create,
        model="gpt-4o-mini",
        messages=msgs,
        temperature=0.7,
        max_tokens=800,
    )
    answer = resp.choices[0].message.content.strip()

    # сохраняем ответ ассистента
    await db_add_message(user_id, "assistant", answer)
    return answer


async def ai_report(user_id: int) -> str:
    """Конечный «Итог» по всей истории диалога пользователя."""
    rows = await db_last_messages(user_id, limit=1000)
    # собираем только текстовые реплики
    convo = []
    for role, content in rows:
        if role in {"user", "assistant"}:
            tag = "Пользователь" if role == "user" else "Наставник"
            convo.append(f"{tag}: {content}")

    prompt = (
        "Ниже переписка. Сформируй краткий и тёплый итог в HTML:\n"
        "1) <b>Сильные стороны</b>\n"
        "2) <b>Ценности</b>\n"
        "3) <b>Где энергия и поток</b>\n"
        "4) <b>Роли/форматы</b> (наброски)\n"
        "5) <b>Малые шаги на 7–10 дней</b>\n\n"
        "Тон: мягкий, вдохновляющий, без коуч-клише. Никаких ссылок на ИИ.\n\n"
        "Переписка:\n" + "\n".join(convo)
    )

    resp = await asyncio.to_thread(
        client.chat.completions.create,
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": "Форматируй строго HTML, без markdown."},
            {"role": "user", "content": prompt},
        ],
        temperature=0.5,
        max_tokens=1400,
    )
    return resp.choices[0].message.content.strip()


# ---------- Хендлеры ----------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    await db_upsert_user(user.id)
    await send_html(update, WELCOME_TEXT)


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    text = (update.effective_message.text or "").strip()

    # Триггеры
    lowered = text.lower()
    if lowered in {"начинаем", "начать", "старт"}:
        await db_add_message(user.id, "assistant", FIRST_QUESTION)
        await send_html(update, FIRST_QUESTION)
        return

    if lowered in {"итог", "покажи итог", "резюме", "отчёт", "отчет"}:
        await send_html(update, "Готовлю твой итог… ⏳")
        report = await ai_report(user.id)
        for chunk in split_for_telegram(report):
            await send_html(update, chunk)
        return

    # Обычная реплика пользователя → ответ наставника
    try:
        answer = await ai_reply(user.id, text)
    except Exception as e:
        log.exception("AI error: %s", e)
        answer = (
            "<b>Небольшая задержка на линии.</b><br><br>"
            "Попробуй написать эту мысль ещё раз — я с тобой. 🌿"
        )

    for chunk in split_for_telegram(answer):
        await send_html(update, chunk)


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    txt = (
        "<b>Команды:</b><br>"
        "• /start — начать заново<br>"
        "• Напиши <b>Начинаем</b> — и я запущу распаковку<br>"
        "• Напиши <b>Итог</b> — пришлю краткое резюме твоего пути"
    )
    await send_html(update, txt)


# ---------- Запуск ----------
def start_bot() -> None:
    app = (
        ApplicationBuilder()
        .token(TOKEN)
        .defaults(  # сразу HTML по умолчанию
            defaults=constants.Defaults(
                parse_mode=constants.ParseMode.HTML,
                disable_web_page_preview=True,
            )
        )
        .build()
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    # инициализация БД перед стартом поллинга
    async def _pre_start():
        await db_init()
        log.info("DB ready")

    app.post_init = _pre_start  # выполнится перед run_polling

    # ВАЖНО: никаких .wait() тут не нужно
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    start_bot()
