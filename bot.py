import os, json, asyncio, time
from collections import deque
from typing import Deque, Dict, List, Tuple, Optional

from telegram import Update, constants
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters

# ===== OpenAI client (динамика ответов) =====
try:
    from openai import OpenAI
except Exception:
    OpenAI = None

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL   = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

def llm_client() -> Optional[OpenAI]:
    if not OPENAI_API_KEY or OpenAI is None:
        return None
    try:
        return OpenAI(api_key=OPENAI_API_KEY)
    except Exception:
        return None

# ===== Telegram & режим =====
TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
MODE  = os.getenv("MODE", "polling").lower()  # оставляем polling

# ===== Память: Postgres (если есть) + in-memory =====
DB_URL = os.getenv("DATABASE_URL")
USE_DB = False
conn = None

if DB_URL:
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
        USE_DB = True
    except Exception:
        conn = None
        USE_DB = False

# in-memory — быстрый кэш, чтобы не бить БД каждой репликой
MEM: Dict[int, Deque[Tuple[str, str]]] = {}
MAX_TURNS_CACHE = 50        # кэш последнего фрагмента
MAX_TURNS_TOTAL = 500       # общий потолок в БД (чтобы не разрасталось бесконечно)

def mem_get(chat_id: int) -> Deque[Tuple[str, str]]:
    if chat_id not in MEM:
        MEM[chat_id] = deque(maxlen=MAX_TURNS_CACHE)
        if USE_DB:
            hist = db_load(chat_id)
            for m in hist[-MAX_TURNS_CACHE:]:
                MEM[chat_id].append((m.get("role","user"), m.get("content","")))
    return MEM[chat_id]

def mem_append(chat_id: int, role: str, content: str):
    dq = mem_get(chat_id)
    dq.append((role, content))
    if USE_DB:
        # грузим полную историю, добавляем запись и обрезаем до MAX_TURNS_TOTAL
        hist = db_load(chat_id)
        hist.append({"role": role, "content": content})
        if len(hist) > MAX_TURNS_TOTAL:
            hist = hist[-MAX_TURNS_TOTAL:]
        db_save(chat_id, hist)

def mem_list(chat_id: int) -> List[Dict]:
    dq = mem_get(chat_id)
    return [{"role": r, "content": c} for r, c in dq]

def mem_clear(chat_id: int):
    MEM[chat_id] = deque(maxlen=MAX_TURNS_CACHE)
    if USE_DB:
        db_save(chat_id, [])

def db_load(chat_id: int) -> List[Dict]:
    if not USE_DB: return []
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT history FROM convo WHERE chat_id=%s;", (chat_id,))
            row = cur.fetchone()
            return row[0] or [] if row else []
    except Exception:
        return []

def db_save(chat_id: int, history: List[Dict]) -> None:
    if not USE_DB: return
    try:
        with conn.cursor() as cur:
            cur.execute("""
            INSERT INTO convo (chat_id, history, updated_at)
            VALUES (%s, %s, NOW())
            ON CONFLICT (chat_id) DO UPDATE SET history = EXCLUDED.history, updated_at = NOW();
            """, (chat_id, json.dumps(history)))
    except Exception:
        pass

# ===== Стиль/промпты =====
SYSTEM_PROMPT = (
    "Ты — AILVI_Guide: тёплый, бережный наставник. Говоришь мягко, на «ты», без указания пола. "
    "Помогаешь распаковать намерения, ценности и естественные силы, затем наводишь на халяльные, этичные способы заработка. "
    "Используй только HTML-разметку (<b>, <i>, <u>, <code>). Никогда не упоминай ChatGPT, OpenAI, модели. "
    "Если спрашивают кто ты — ты AILVI_Guide, наставник и компас. Избегай харама. Отвечай коротко, по делу и тепло."
)

WARM_START = (
    "✨ <b>Рад(а) приветствовать тебя.</b>\n"
    "Здесь безопасно и спокойно. Я рядом, чтобы помочь раскрыться безоценочно и по-настоящему.\n\n"
    "Чтобы начать распаковку — напиши: <b>Начинаем</b> ✨"
)

WARM_AFTER_BEGIN = (
    "🌿 <b>Начнём с самого важного для тебя сейчас.</b>\n"
    "Одним словом или фразой — к чему тянется сердце сегодня?\n\n"
    "Подсказки: <i>«призвание»</i>, <i>«внутреннее состояние»</i>, <i>«отношения с делом»</i>, <i>«ясность в шагах»</i>."
)

WORK_BRIDGE = (
    "Вижу, про работу важно. Мы обязательно сделаем её ясной и практичной. "
    "И всё же начнём с основания — с того, что внутри. Это поможет выбрать не случайную деятельность, а живую и устойчивую. "
    "Напиши одним словом, что сейчас звучит сильнее всего. 💬"
)

# ===== Генерация =====
async def llm_reply(chat_id: int, user_text: str) -> str:
    low = user_text.strip().lower()
    if any(k in low for k in ["ты кто", "кто ты", "что ты", "chatgpt", "openai", "gpt"]):
        return (
            "<b>Я — AILVI_Guide.</b> Тёплый наставник и компас: помогаю распаковать твои сильные стороны, "
            "привести сердце в ясность и найти халяльные пути заработка. Пойдём бережно, шаг за шагом. 🌿"
        )

    client = llm_client()
    if not client:
        return ("Я тебя слышу. Давай коротко: одним словом — к чему зовёт сердце прямо сейчас? ✨")

    # собираем контекст (system + полная память из БД + кэш последних ходов)
    full_hist = db_load(chat_id) if USE_DB else []
    short_hist = mem_list(chat_id)  # кэш последних ходов
    messages = [{"role":"system","content":SYSTEM_PROMPT}]
    messages.extend(full_hist[-40:])        # даём модели разумный фрагмент (контроль стоимости)
    messages.extend(short_hist[-10:])       # плюс свежий локальный контекст
    messages.append({"role":"user","content":user_text})

    try:
        res = client.chat.completions.create(
            model=OPENAI_MODEL, messages=messages,
            temperature=0.6, max_tokens=700, top_p=0.95
        )
        text = res.choices[0].message.content.strip()
        return text.replace("**","").replace("__","")
    except Exception:
        return ("Сейчас мне трудно с генерацией. Давай по-простому: какое слово звучит сильнее всего? 🌿")

# ===== Команды =====
async def cmd_health(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("OK")

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    mem_clear(chat_id)
    mem_append(chat_id, "assistant", WARM_START)
    await update.message.reply_html(WARM_START)

async def cmd_reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    mem_clear(chat_id)
    await update.message.reply_html("Память очищена. Чтобы начать заново — напиши: <b>Начинаем</b> ✨")

async def cmd_summary(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Собираю итог по всей истории и присылаю как сообщения."""
    chat_id = update.effective_chat.id
    client = llm_client()
    hist = db_load(chat_id) if USE_DB else mem_list(chat_id)
    if not hist:
        await update.message.reply_html("Пока история пуста. Начнём с <b>Начинаем</b> ✨")
        return

    if not client:
        await update.message.reply_html(
            "Ключ генерации сейчас недоступен. Но ты можешь коротко описать, что уже понял(а), "
            "и я помогу упаковать это в план.")
        return

    prompt = (
        "На основе истории диалога ниже сделай короткий, тёплый и очень практичный итог для человека. "
        "Структура HTML:\n"
        "<b>1) Что стало яснее</b> — 3–6 пунктов;\n"
        "<b>2) Сильные стороны</b> — 3–6 пунктов;\n"
        "<b>3) Мягкие рекомендации на 7 дней</b> — 5–8 шагов (простые, выполнимые);\n"
        "<b>4) Вдохновляющее напоминание</b> — 2–3 строки.\n"
        "Не упоминай модели/бренды. Уважай Ислам (никакого харама). История:\n\n"
        + json.dumps(hist[-200:], ensure_ascii=False)
    )

    try:
        res = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[{"role":"system","content":SYSTEM_PROMPT},
                      {"role":"user","content":prompt}],
            temperature=0.5, max_tokens=1200
        )
        text = res.choices[0].message.content.strip()
        # Telegram ограничивает длину сообщения — разобьём, если нужно
        chunks: List[str] = []
        while text:
            chunks.append(text[:3500])
            text = text[3500:]
        for ch in chunks:
            await update.message.reply_html(ch, disable_web_page_preview=True)
    except Exception:
        await update.message.reply_html("Не получилось собрать итог сейчас. Попробуем ещё раз чуть позже.")

# ===== Роутер сообщений =====
async def router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return
    chat_id = update.effective_chat.id
    text = update.message.text.strip()

    if text.lower().startswith("начинаем"):
        mem_append(chat_id, "user", text)
        mem_append(chat_id, "assistant", WARM_AFTER_BEGIN)
        await update.message.reply_html(WARM_AFTER_BEGIN)
        return

    low = text.lower()
    if any(w in low for w in ["работ", "деньг", "заработ", "вакан", "професс"]):
        mem_append(chat_id, "user", text)
        mem_append(chat_id, "assistant", WORK_BRIDGE)
        await update.message.reply_html(WORK_BRIDGE)
        return

    mem_append(chat_id, "user", text)
    reply = await llm_reply(chat_id, text)
    mem_append(chat_id, "assistant", reply)
    await update.message.reply_html(reply, disable_web_page_preview=True)

# ===== Запуск =====
def build_app() -> Application:
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("health",  cmd_health))
    app.add_handler(CommandHandler("start",   cmd_start))
    app.add_handler(CommandHandler("reset",   cmd_reset))
    app.add_handler(CommandHandler("summary", cmd_summary))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, router))
    return app

if __name__ == "__main__":
    application = build_app()
    # простой, надёжный лайф-цикл без ручного updater.stop() — ошибка исчезнет
    application.run_polling(allowed_updates=constants.ALL_UPDATE_TYPES, poll_interval=1.5)
