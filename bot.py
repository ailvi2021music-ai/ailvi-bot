import os
import re
import math
import json
import threading
from datetime import datetime, timezone
from typing import List, Dict
from textwrap import shorten

from flask import Flask
from openai import OpenAI
from telegram.ext import ApplicationBuilder, MessageHandler, CommandHandler, filters

import psycopg
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

# -------------------------
# 🔑 Переменные окружения
# -------------------------
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")

client = OpenAI(api_key=OPENAI_API_KEY)

# -------------------------
# 🗄️ Postgres (пул + миграции)
# -------------------------
pool = ConnectionPool(conninfo=DATABASE_URL, kwargs={"autocommit": True})

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS users (
  user_id BIGINT PRIMARY KEY,
  first_seen TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS messages (
  id BIGSERIAL PRIMARY KEY,
  user_id BIGINT NOT NULL,
  role TEXT NOT NULL CHECK (role IN ('user','assistant','system')),
  content TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_messages_user_id_created_at ON messages(user_id, created_at);

CREATE TABLE IF NOT EXISTS progress (
  user_id BIGINT PRIMARY KEY,
  intention BOOLEAN DEFAULT FALSE,
  episodes BOOLEAN DEFAULT FALSE,
  values BOOLEAN DEFAULT FALSE,
  energy BOOLEAN DEFAULT FALSE,
  flow BOOLEAN DEFAULT FALSE,
  rbs BOOLEAN DEFAULT FALSE,
  traits BOOLEAN DEFAULT FALSE,
  strengths BOOLEAN DEFAULT FALSE,
  interests BOOLEAN DEFAULT FALSE,
  skills BOOLEAN DEFAULT FALSE,
  environment BOOLEAN DEFAULT FALSE,
  roles BOOLEAN DEFAULT FALSE,
  hypotheses BOOLEAN DEFAULT FALSE,
  experiments BOOLEAN DEFAULT FALSE,
  strategy BOOLEAN DEFAULT FALSE,
  offered_summary_at TIMESTAMPTZ,
  summary_sent_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS summaries (
  id BIGSERIAL PRIMARY KEY,
  user_id BIGINT NOT NULL,
  summary_text TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
"""

# -------------------------
# 🌿 Тексты и капсулы
# -------------------------
WELCOME_TEXT = (
    "Ассаляму Алейкум уа РахматуЛлахи уа Баракятух! 👋🏻\n\n"
    "Добро пожаловать в пространство, где Сердце узнаёт себя заново.\n\n"
    "Давай вместе, спокойно, шаг за шагом откроем дары, которые Аллах уже вложил в твою Душу — силы, таланты, намерения. 💎\n\n"
    "Пусть Аллах сделает этот путь лёгким, благословенным и наполненным пониманием!\n\n"
    "Чтобы начать глубокую распаковку — напиши: «Начинаем»"
)

SYSTEM_CAPSULE = (
    "Ты — мягкий, спокойный, внимательный проводник AILVI. "
    "Говоришь нейтрально (без указания пола), тепло и бережно. "
    "Ведёшь живую распаковку личности: каждый следующий шаг рождается из ответа собеседника. "
    "Без давления и мотивационных клише. Атмосфера Ислама достойная и мягкая; цитаты Корана/хадисов — только по запросу. "
    "Пиши простым русским, допускай уместные эмодзи. "
    "Цель: помочь увидеть ценности, сильные стороны, естественные роли и среду. "
    "Если человека тянет сразу к деньгам — мягко возвращай к глубине, затем связывай с профессиональными гипотезами. "
    "Слово «ризк» писать именно так: ризк."
)

# Модули пути (сверим чек-лист прогресса; когда все True — предложим итог)
MODULE_KEYS = [
    "intention", "episodes", "values", "energy", "flow", "rbs",
    "traits", "strengths", "interests", "skills", "environment",
    "roles", "hypotheses", "experiments", "strategy"
]

# -------------------------
# ✅ Flask health-check
# -------------------------
app = Flask(__name__)

@app.route("/")
def home():
    return "AILVI bot is alive"

def run_flask():
    app.run(host="0.0.0.0", port=10000)

# -------------------------
# 🧠 DB helpers
# -------------------------
def init_db():
    with pool.connection() as conn, conn.cursor() as cur:
        cur.execute(SCHEMA_SQL)

def ensure_user(user_id: int):
    with pool.connection() as conn, conn.cursor() as cur:
        cur.execute("INSERT INTO users(user_id) VALUES (%s) ON CONFLICT DO NOTHING;", (user_id,))
        cur.execute("INSERT INTO progress(user_id) VALUES (%s) ON CONFLICT DO NOTHING;", (user_id,))

def save_message(user_id: int, role: str, content: str):
    with pool.connection() as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO messages(user_id, role, content) VALUES (%s, %s, %s);",
            (user_id, role, content),
        )

def fetch_context(user_id: int, limit: int = 20):
    """Окно контекста для модели (экономим токены). Хранилище — полное, тут только подача в модель."""
    with pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            SELECT role, content
            FROM messages
            WHERE user_id = %s AND role IN ('user','assistant')
            ORDER BY created_at DESC
            LIMIT %s;
            """,
            (user_id, limit),
        )
        rows = cur.fetchall()
    rows.reverse()
    return [{"role": r["role"], "content": r["content"]} for r in rows]

def fetch_all_messages(user_id: int):
    with pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            "SELECT role, content, created_at FROM messages WHERE user_id = %s ORDER BY created_at ASC;",
            (user_id,),
        )
        return cur.fetchall()

def get_progress(user_id: int) -> Dict[str, bool]:
    with pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        cur.execute("SELECT * FROM progress WHERE user_id = %s;", (user_id,))
        row = cur.fetchone()
    if not row:
        return {k: False for k in MODULE_KEYS}
    return {k: bool(row[k]) for k in MODULE_KEYS}

def set_progress_flags(user_id: int, updates: Dict[str, bool]):
    if not updates:
        return
    sets = []
    vals = []
    for k, v in updates.items():
        if k in MODULE_KEYS:
            sets.append(f"{k} = %s")
            vals.append(bool(v))
    if not sets:
        return
    vals.append(user_id)
    with pool.connection() as conn, conn.cursor() as cur:
        cur.execute(f"UPDATE progress SET {', '.join(sets)} WHERE user_id = %s;", vals)

def mark_offered(user_id: int):
    with pool.connection() as conn, conn.cursor() as cur:
        cur.execute("UPDATE progress SET offered_summary_at = NOW() WHERE user_id = %s;", (user_id,))

def mark_summary_sent(user_id: int):
    with pool.connection() as conn, conn.cursor() as cur:
        cur.execute("UPDATE progress SET summary_sent_at = NOW() WHERE user_id = %s;", (user_id,))

def get_offer_status(user_id: int):
    with pool.connection() as conn, conn.cursor(row_factory=dict_row) as cur:
        cur.execute("SELECT offered_summary_at, summary_sent_at FROM progress WHERE user_id = %s;", (user_id,))
        row = cur.fetchone()
    return row["offered_summary_at"], row["summary_sent_at"]

def save_summary(user_id: int, text: str):
    with pool.connection() as conn, conn.cursor() as cur:
        cur.execute("INSERT INTO summaries(user_id, summary_text) VALUES (%s, %s);", (user_id, text))

# -------------------------
# 🧭 Классификация шага (без показа пользователю)
# -------------------------
CLASSIFIER_SYSTEM = (
    "Ты — ассистент-классификатор AILVI. Получишь кусочек диалога (несколько последних реплик). "
    "Определи, какие из модулей пути были покрыты содержательно. Верни JSON с булевыми полями:\n"
    "{intention, episodes, values, energy, flow, rbs, traits, strengths, interests, "
    "skills, environment, roles, hypotheses, experiments, strategy}\n"
    "Ставь true только если по этому модулю пользователь дал осмысленные данные или обсуждение явно состоялось. "
    "Без текста, только JSON."
)

def classify_progress_from_context(context_messages: List[Dict[str, str]]) -> Dict[str, bool]:
    snippet = "\n".join(f"{m['role']}: {m['content']}" for m in context_messages[-8:])  # последние 8 реплик
    resp = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": CLASSIFIER_SYSTEM},
            {"role": "user", "content": snippet}
        ],
        temperature=0
    )
    txt = resp.choices[0].message.content or "{}"
    try:
        data = json.loads(txt)
        return {k: bool(data.get(k, False)) for k in MODULE_KEYS}
    except Exception:
        return {}

def all_modules_done(progress: Dict[str, bool]) -> bool:
    return all(progress.get(k, False) for k in MODULE_KEYS)

# -------------------------
# 📜 Итоговая сборка (из всей истории)
# -------------------------
CHUNK_SIZE = 80

SUMMARY_SYSTEM = (
    "Ты — аналитик AILVI. Получишь историю диалога (user/assistant). "
    "Сначала извлеки факты и маркеры из этих сообщений без домыслов, списком."
)

SUMMARY_USER_INSTR = (
    "Извлеки из блока диалога только то, что относится к личности пользователя. "
    "Верни JSON со структурами: {"
    "\"values\": [строки], "
    "\"strengths\": [строки], "
    "\"interests\": [строки], "
    "\"environments\": [строки], "
    "\"roles\": [строки], "
    "\"motivators\": [строки], "
    "\"drainers\": [строки], "
    "\"blockers\": [строки], "
    "\"examples\": [краткие цитаты пользователя]"
    "}. Без пояснений, только JSON."
)

MERGE_SYSTEM = (
    "Ты — аналитик AILVI. Объедини несколько JSON-выжимок в единую, устранив повторы и противоречия."
)

FINAL_SYSTEM = (
    "Ты — проводник AILVI. На основе объединённого JSON создай ясный итог для человека: "
    "1) Ценности (5–9)  2) Сильные стороны (5–9)  3) Естественная среда  "
    "4) Возможные роли (2–4)  5) Мотиваторы и дренаж  6) Три гипотезы призвания (формула «Я силён в…, люблю…, миру нужно…»)  "
    "7) Идеи 2–3 микро-экспериментов на 7–10 дней  8) Тихая рекомендация по режиму/среде. "
    "Тон мягкий, без пола, с уместными эмодзи. Короткие абзацы и списки."
)

def _ask_openai(messages, temperature=0.2):
    resp = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=messages,
        temperature=temperature,
    )
    return resp.choices[0].message.content

def build_final_summary_for_user(user_id: int) -> str:
    data = fetch_all_messages(user_id)
    if not data:
        return "История пока пуста. Давай начнём с «Начинаем». 🌿"

    chunks = [data[i:i+CHUNK_SIZE] for i in range(0, len(data), CHUNK_SIZE)]
    json_summaries = []
    for chunk in chunks:
        text_block = "\n".join(
            f"[{row['created_at'].isoformat()}] {row['role']}: {row['content']}"
            for row in chunk
        )
        j = _ask_openai([
            {"role": "system", "content": SUMMARY_SYSTEM},
            {"role": "user", "content": SUMMARY_USER_INSTR + "\n\n---\n" + text_block}
        ])
        json_summaries.append(j)

    merged = _ask_openai([
        {"role": "system", "content": MERGE_SYSTEM},
        {"role": "user", "content": "Объедини эти JSON-выжимки:\n" + "\n\n".join(json_summaries)}
    ])

    final_text = _ask_openai([
        {"role": "system", "content": FINAL_SYSTEM},
        {"role": "user", "content": merged}
    ], temperature=0.4)

    return final_text

# -------------------------
# 📨 НЛУ: согласие/отказ на показ итога
# -------------------------
YES_PAT = re.compile(r"\b(да|давай|покажи|хочу|готов|итог|резюме|давай\s*итог|давай\s*резюме)\b", re.I)
NO_PAT  = re.compile(r"\b(пока\s*нет|не\s*сейчас|потом|не нужно|не надо)\b", re.I)

def is_yes(text: str) -> bool:
    return bool(YES_PAT.search(text or ""))

def is_no(text: str) -> bool:
    return bool(NO_PAT.search(text or ""))

# -------------------------
# 🤖 Телеграм-логика
# -------------------------
def first_prompt_after_begin():
    return (
        "С радостью начинаю распаковку. ✨\n"
        "Расскажи, какой большой вопрос у тебя сейчас на сердце — "
        "про смысл, призвание, отношения с работой или ощущение себя? "
        "Примеры: «не понимаю, где моя сила», «хочу ясности в работе», "
        "«чувствую усталость и хочу перемен». Можешь коротко. 🌿"
    )

async def start(update, context):
    user = update.effective_user
    ensure_user(user.id)
    save_message(user.id, "assistant", WELCOME_TEXT)
    await update.message.reply_text(WELCOME_TEXT)

async def handle_message(update, context):
    user = update.effective_user
    text = (update.message.text or "").strip()
    ensure_user(user.id)

    # Стартовая реплика
    if text.lower() in ("начинаем", "начать", "start"):
        prompt = first_prompt_after_begin()
        save_message(user.id, "assistant", prompt)
        await update.message.reply_text(prompt)
        return

    # Сохраняем пользовательскую реплику
    save_message(user.id, "user", text)

    # Проверяем: если ранее мы предложили итог и человек согласен — показываем
    offered_at, summary_sent_at = get_offer_status(user.id)
    if offered_at and not summary_sent_at and is_yes(text):
        await send_summary_messages(user.id, update)
        return
    if offered_at and not summary_sent_at and is_no(text):
        # Мягко продолжаем без итога
        reply = "Хорошо, оставим итог на потом. Продолжим движение мягко и без спешки. 🌿"
        save_message(user.id, "assistant", reply)
        await update.message.reply_text(reply)
        return

    # Генерируем ответ по «окну» + системной капсуле
    history = [{"role": "system", "content": SYSTEM_CAPSULE}]
    history += fetch_context(user.id, limit=20)

    try:
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=history,
            temperature=0.6,
        )
        answer = resp.choices[0].message.content
    except Exception:
        answer = "Кажется, возникла техническая пауза. Попробуем ещё раз через мгновение. 🌿"

    save_message(user.id, "assistant", answer)
    await update.message.reply_text(answer)

    # После ответа обновим прогресс по классификатору и при необходимости предложим итог
    try:
        ctx_for_cls = fetch_context(user.id, limit=20)
        flags = classify_progress_from_context(ctx_for_cls)
        set_progress_flags(user.id, flags)

        progress = get_progress(user.id)
        offered_at, summary_sent_at = get_offer_status(user.id)

        if all_modules_done(progress) and not offered_at and not summary_sent_at:
            offer = (
                "Похоже, мы собрали все важные кусочки твоей картины. ✨ "
                "Хочешь, соберу и покажу аккуратный итог: ценности, сильные стороны, естественную среду, роли, "
                "три гипотезы призвания и идеи микро-экспериментов? Ответь просто «да» — и я пришлю."
            )
            mark_offered(user.id)
            save_message(user.id, "assistant", offer)
            await update.message.reply_text(offer)
    except Exception:
        # Тихо игнорируем сбой классификатора — диалог не должен ломаться
        pass

async def send_summary_messages(user_id: int, update):
    await update.message.reply_text("Формирую твой аккуратный итог… это займёт минутку. 📜")
    try:
        final_text = build_final_summary_for_user(user_id)
        save_summary(user_id, final_text)
        mark_summary_sent(user_id)

        MAX_LEN = 3500
        parts = [final_text[i:i+MAX_LEN] for i in range(0, len(final_text), MAX_LEN)]
        for idx, p in enumerate(parts, 1):
            header = f"Итог (часть {idx}/{len(parts)}):\n\n" if len(parts) > 1 else ""
            await update.message.reply_text(header + p)
    except Exception:
        await update.message.reply_text("Не вышло собрать итог прямо сейчас. Попробуем чуть позже. 🌿")

def run_telegram():
    application = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()
    # /start нужен только для первого приветствия — кнопок и команд для пользователя больше нет
    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print("✅ Telegram polling started")
    application.run_polling()

# -------------------------
# 🚀 Main
# -------------------------
if __name__ == "__main__":
    init_db()

    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()

    run_telegram()
