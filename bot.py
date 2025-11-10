import os
import asyncio
import json
import time
from collections import deque
from typing import Deque, Dict, List, Tuple, Optional

from telegram import Update, constants
from telegram.ext import (
    Application, CommandHandler, MessageHandler, ContextTypes, filters
)

# === LLM (OpenAI) ===
# pip install openai==1.51.2
try:
    from openai import OpenAI
except Exception:
    OpenAI = None

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")  # можно поменять при желании

# === Режимы и токены ===
TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
MODE = os.getenv("MODE", "polling").lower()  # оставляем polling по умолчанию

# === Простая «память» ===
# 1) In-memory (дефолт, быстрая)
MEMORY: Dict[int, Deque[Tuple[str, str]]] = {}  # chat_id -> deque of (role, content)
MAX_TURNS = 20

# 2) Постгрес (опционально)
DB_URL = os.getenv("DATABASE_URL")
USE_DB = bool(DB_URL)
conn = None
if USE_DB:
    try:
        import psycopg
        conn = psycopg.connect(DB_URL, autocommit=True)
        with conn.cursor() as cur:
            cur.execute("""
            CREATE TABLE IF NOT EXISTS convo (
                chat_id BIGINT PRIMARY KEY,
                history JSONB NOT NULL DEFAULT '[]'::jsonb,
                updated_at TIMESTAMP DEFAULT NOW()
            );
            """)
    except Exception as e:
        # Если БД не взлетела — просто не используем её
        conn = None
        USE_DB = False


def db_load_history(chat_id: int) -> List[Dict]:
    if not USE_DB:
        return []
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT history FROM convo WHERE chat_id=%s;", (chat_id,))
            row = cur.fetchone()
            if not row:
                return []
            return row[0] or []
    except Exception:
        return []


def db_save_history(chat_id: int, history: List[Dict]) -> None:
    if not USE_DB:
        return
    try:
        with conn.cursor() as cur:
            cur.execute("""
            INSERT INTO convo (chat_id, history, updated_at)
            VALUES (%s, %s, NOW())
            ON CONFLICT (chat_id) DO UPDATE SET history = EXCLUDED.history, updated_at = NOW();
            """, (chat_id, json.dumps(history)))
    except Exception:
        pass


def mem_get(chat_id: int) -> Deque[Tuple[str, str]]:
    if chat_id not in MEMORY:
        MEMORY[chat_id] = deque(maxlen=MAX_TURNS)
        # если есть база — подтянем историю при первом обращении
        hist = db_load_history(chat_id)
        for m in hist[-MAX_TURNS:]:
            MEMORY[chat_id].append((m.get("role","user"), m.get("content","")))
    return MEMORY[chat_id]


def mem_to_list(chat_id: int) -> List[Dict]:
    dq = mem_get(chat_id)
    return [{"role": r, "content": c} for (r, c) in dq]


def mem_append(chat_id: int, role: str, content: str) -> None:
    dq = mem_get(chat_id)
    dq.append((role, content))
    # в БД сохраняем всю очередь
    if USE_DB:
        db_save_history(chat_id, [{"role": r, "content": c} for r, c in dq])


SYSTEM_PROMPT = (
    "Ты — AILVI_Guide: тёплый, бережный наставник. "
    "Говоришь мягко и уважительно, на «ты», без указания пола. "
    "Главная цель — помочь человеку распаковать себя (намерения, ценности, естественные силы), "
    "а затем вести к халяльным, этичным способам заработка. "
    "Отвечай кратко, по делу, но с душой. "
    "Используй HTML-разметку (<b></b>, <i></i>, <u></u>, <code></code>), без Markdown. "
    "Не раскрывай и не обсуждай происхождение модели, OpenAI и т.п. "
    "Если собеседник спрашивает, кто ты — ты AILVI_Guide: «наставник и компас», без брендов. "
    "Если человек пишет про работу раньше распаковки — мягко перенаправь к внутренней ясности, "
    "объяснив почему это поможет. "
    "Помни про Ислам: избегай харама, поддерживай честность и чистый ризк. "
)

WARM_START = (
    "✨ <b>Рад(а) приветствовать тебя.</b>\n"
    "Это безопасное пространство без оценок. Я рядом, чтобы помочь раскрыться спокойно и по-настоящему.\n\n"
    "Чтобы начать глубокую распаковку — напиши: <b>Начинаем</b> ✨"
)

WARM_AFTER_BEGIN = (
    "🌿 <b>Начнём с самого важного для тебя сейчас.</b>\n"
    "Расскажи кратко, к чему тянется сердце прямо сегодня — одним словом или фразой.\n\n"
    "Варианты-подсказки:\n"
    "— <i>смысл / призвание</i>\n"
    "— <i>внутреннее состояние</i>\n"
    "— <i>отношения с работой / делом</i>\n"
    "— <i>ясность в шагах</i>\n\n"
    "Можешь написать, например: «призвание», «ясность в шагах». Я бережно поведу дальше. 🌙"
)

WORK_BRIDGE = (
    "Вижу, тема работы важна. Мы обязательно сделаем её ясной и практичной. "
    "И всё же начнём с основания — с того, что внутри. Это поможет выбрать не «случайную» деятельность, "
    "а живую и устойчивую. Напиши одним словом, что сейчас звучит сильнее всего внутри. 💬"
)


def llm_client() -> Optional[OpenAI]:
    if not OPENAI_API_KEY or OpenAI is None:
        return None
    try:
        return OpenAI(api_key=OPENAI_API_KEY)
    except Exception:
        return None


async def generate(chat_id: int, user_text: str) -> str:
    """
    Генерируем ответ. Если ключа нет — даём разумный локальный ответ,
    чтобы чат не ломался.
    """
    # Быстрые «системные» перехваты
    low = user_text.strip().lower()
    if any(q in low for q in ["ты кто", "кто ты", "что ты", "chatgpt", "openai", "gpt"]):
        return (
            "<b>Я — AILVI_Guide.</b> Тёплый наставник и компас: помогаю распаковать твои сильные стороны, "
            "привести сердце в ясность и найти халяльные пути заработка. Пойдём бережно, шаг за шагом. 🌿"
        )

    client = llm_client()
    history = mem_to_list(chat_id)

    # Сбор сообщений для модели
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]

    # Добавляем последние реплики чата
    for m in history[-MAX_TURNS:]:
        messages.append(m)

    messages.append({"role": "user", "content": user_text})

    if client is None:
        # Fallback без LLM — короткий эмпатичный ответ
        return (
            "Я тебя слышу. Давай сделаем так: напиши, что сейчас звучит сильнее всего — "
            "<i>«призвание»</i>, <i>«внутреннее состояние»</i>, <i>«отношения с делом»</i> или "
            "<i>«ясность в шагах»</i>. От этого мы аккуратно пойдём дальше. ✨"
        )

    try:
        resp = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=messages,
            temperature=0.6,
            max_tokens=700,
            top_p=0.95,
        )
        text = resp.choices[0].message.content.strip()
        # страхуемся: если вдруг модель вернула Markdown, просим быть в HTML
        # (простая авто-замена **…** -> <b>…</b> / _…_ -> <i>…</i> не всегда надёжна,
        # поэтому лишь мягко подчищаем очевидное)
        text = text.replace("**", "").replace("__", "")
        return text
    except Exception:
        return (
            "Сейчас у меня трудность с генерацией ответа. Давай коротко и по-простому: "
            "одним словом — к чему зовёт сердце прямо сейчас? 🌿"
        )


# === Handlers ===

async def health(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("OK")


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    # начинаем новую лёгкую историю
    MEMORY[chat_id] = deque(maxlen=MAX_TURNS)
    mem_append(chat_id, "assistant", WARM_START)
    await update.message.reply_html(WARM_START)


async def message_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return
    chat_id = update.effective_chat.id
    text = update.message.text.strip()

    # Примитивное состояние: «Начинаем»
    if text.lower().startswith("начинаем"):
        mem_append(chat_id, "user", text)
        mem_append(chat_id, "assistant", WARM_AFTER_BEGIN)
        await update.message.reply_html(WARM_AFTER_BEGIN, disable_web_page_preview=True)
        return

    # Если человек сразу «работа», «деньги» и т.п., мягко мостим к глубине
    lower = text.lower()
    if any(w in lower for w in ["работ", "деньг", "заработ", "вакан", "професс"]):
        mem_append(chat_id, "user", text)
        mem_append(chat_id, "assistant", WORK_BRIDGE)
        await update.message.reply_html(WORK_BRIDGE, disable_web_page_preview=True)
        return

    # Обычный диалог — динамическая генерация
    mem_append(chat_id, "user", text)
    reply = await generate(chat_id, text)
    mem_append(chat_id, "assistant", reply)
    await update.message.reply_html(reply, disable_web_page_preview=True)


def build_app() -> Application:
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("health", health))
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, message_router))
    return app


async def main():
    app = build_app()
    # режим polling — надёжен на free-плане, без портов
    await app.initialize()
    await app.start()
    print("Bot started (polling).")
    try:
        await app.updater.start_polling(allowed_updates=constants.ALL_UPDATE_TYPES)
        # держим процесс живым
        while True:
            await asyncio.sleep(3600)
    finally:
        await app.updater.stop()
        await app.stop()
        await app.shutdown()

if __name__ == "__main__":
    asyncio.run(main())
import os
import re
import logging
from typing import Optional

from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    ContextTypes,
    MessageHandler,
    CommandHandler,
    filters,
)

# ---------------------- ЛОГИ ----------------------
logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO,
)
log = logging.getLogger("ailvi-bot")

# ---------------------- НАСТРОЙКИ ----------------------
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
MODE = os.getenv("MODE", "polling").strip().lower()  # polling | webhook (мы используем polling)

if not TOKEN:
    raise RuntimeError("TELEGRAM_BOT_TOKEN отсутствует в переменных окружения.")

# ---------------------- ТЕКСТЫ (HTML) ----------------------
WELCOME_TEXT = (
    "<b>Ассаляму Алейкум уа РахматуЛлахи уа Баракятух!</b> 👋🏻\n\n"
    "Добро пожаловать в пространство, где <b>Сердце</b> узнаёт себя заново.\n\n"
    "Пойдём мягко, шаг за шагом, чтобы открыть дары, которые Аллах уже вложил "
    "в твою душу — силы, таланты и намерения, которые ждут, когда ты увидишь их свет. 💎\n\n"
    "Пусть Аллах сделает этот путь лёгким, благословенным и наполненным пониманием!\n\n"
    "Чтобы начать глубокую распаковку — напиши: <b>Начинаем</b> ✨"
)

FIRST_DEEP_PROMPT = (
    "Начнём с самого важного для тебя сейчас. ✨\n\n"
    "Скажи коротко, какая область зовёт сильнее всего сегодня:\n"
    "— <i>смысл/призвание</i>,\n"
    "— <i>внутреннее состояние</i>,\n"
    "— <i>отношения с работой/делом</i>,\n"
    "— <i>ясность в шагах</i>.\n\n"
    "Напиши одним словом или фразой (например: «призвание», «ясность в шагах»)."
)

BRIDGE_TO_DEPTH = (
    "Понимаю, тема работы важна. И чтобы решение было <b>живым и устойчивым</b>, "
    "пройдём короткую внутреннюю настройку:\n\n"
    "1) Что из того, что ты делал(а) когда-либо, приносило <b>тихую радость</b>? ✨\n"
    "2) В каких моментах ты чувствовал(а): «<i>это по-настоящему моё</i>»?\n"
    "3) Какая польза для людей откликается сердцу — <i>какому человеку ты хочешь помочь и в чём</i>?\n\n"
    "Ответь коротко. Из этого сложим направление и первые шаги. 🌿"
)

GENTLE_PROGRESS = (
    "Это нормально — быть в поиске. Давай поможем сердцу заговорить:\n\n"
    "— Назови 2–3 занятия, где ты забываешь о времени.\n"
    "— Что тебя <i>утомляет</i> больше всего (это поможет понять, чего не брать)?\n"
    "— Какая простая польза для людей вдохновляет (без пафоса — по-доброму и реально)?"
)

IDENTITY_DEFLECT = (
    "Я — твой бережный проводник и диалоговый помощник внутри проекта AILVI. 🌿\n"
    "Моя задача — аккуратно наводить ясность, задавать правильные вопросы и держать направление: "
    "исламские ориентиры, мягкость, польза и шаги к делу."
)

INTENT_WORK_KEYWORDS = [
    "работ", "карьер", "вакан", "деньг", "доход", "профес", "дело", "зараб"
]
ASKS_IDENTITY = re.compile(r"(openai|gpt|chatgpt|чатгпт|кто ты|что ты|какая ты модель)", re.I)

def mentions_work(text: str) -> bool:
    t = text.lower()
    return any(k in t for k in INTENT_WORK_KEYWORDS)

def is_unknown(text: str) -> bool:
    return text.strip().lower() in {"не знаю", "не знаю.", "не уверен", "не уверена", "не понимаю"}

# ---------------------- HANDLERS ----------------------
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_html(WELCOME_TEXT, disable_web_page_preview=True)

async def cmd_reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_html("Память диалога очищена. Можем начать заново: напиши <b>Начинаем</b>.")

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (update.message.text or "").strip()

    if ASKS_IDENTITY.search(text):
        await update.message.reply_html(IDENTITY_DEFLECT)
        return

    if text.lower() == "начинаем":
        context.user_data["phase"] = "onboarding1"
        await update.message.reply_html(FIRST_DEEP_PROMPT)
        return

    if "phase" not in context.user_data:
        await update.message.reply_html("Чтобы начать распаковку — напиши: <b>Начинаем</b> ✨")
        return

    if mentions_work(text):
        context.user_data["phase"] = "work_bridge"
        await update.message.reply_html(BRIDGE_TO_DEPTH)
        return

    if is_unknown(text):
        await update.message.reply_html(GENTLE_PROGRESS)
        return

    history = context.user_data.setdefault("notes", [])
    if len(text) <= 800:
        history.append(text)

    followups = [
        "Отмечу. Что из сказанного для тебя самое живое <i>сейчас</i>?",
        "Если сузить фокус до одного шага на 7 дней — какой шаг будет самым добрым и реальным? ✍️",
        "Представь человека, которому это принесёт пользу. Кто он и чем ты можешь быть ему полезен(на)?",
        "Хочешь, я соберу из ответов короткий перечень твоих опор и шагов?",
    ]

    i = context.user_data.setdefault("followup_idx", 0)
    msg = followups[i % len(followups)]
    context.user_data["followup_idx"] = i + 1

    await update.message.reply_html(msg)

async def cmd_health(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("OK")

def main():
    app = ApplicationBuilder().token(TOKEN).build()  # ВАЖНО: без .parse_mode()

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("reset", cmd_reset))
    app.add_handler(CommandHandler("health", cmd_health))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    log.info("Application started (polling)")
    app.run_polling(close_loop=False)

if __name__ == "__main__":
    main()
