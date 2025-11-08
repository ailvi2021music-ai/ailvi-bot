import os
import json
import threading
import logging
from flask import Flask
from telegram import Update
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    ContextTypes, filters
)
from openai import OpenAI

# -------------------------
# 🔧 Логи
# -------------------------
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("ailvi-live")

# -------------------------
# 🔑 Ключи
# -------------------------
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
client = OpenAI(api_key=OPENAI_API_KEY)

# -------------------------
# ✅ Flask health-check
# -------------------------
app = Flask(__name__)

@app.route("/")
def home():
    return "AILVI live-unpack is alive"

def run_flask():
    app.run(host="0.0.0.0", port=10000)

# -------------------------
# 🧭 21 «маяк» (этапы) — для понятных заголовков
# (это НЕ жёсткий сценарий; двигатель сам решает, на каком этапе мы)
# -------------------------
MILESTONES = [
    "Намерение и рамка",                 # 1
    "Три эпизода живости",               # 2
    "Карта ценностей",                   # 3
    "Энергия / Дренаж",                  # 4
    "Поток и условия",                   # 5
    "Внешний взгляд (RBS)",              # 6
    "Свод фактов без выводов",           # 7
    "Черты (Big Five — поведение)",      # 8
    "Сильные стороны (VIA — в действиях)",# 9
    "Интересы (RIASEC — форматы)",       # 10
    "Навыки и Т-профиль",                # 11
    "Среда раскрытия",                   # 12
    "Естественные роли",                 # 13
    "Гипотезы призвания",                # 14
    "Идеи микро-экспериментов",          # 15
    "Дизайн среды под эксперимент",      # 16
    "Запуск первой пробы",               # 17
    "Лог наблюдений",                    # 18
    "Корректировка",                     # 19
    "Вторая проба / мини-питч",          # 20
    "Личная стратегия 1-листом"          # 21
]

# -------------------------
# 🧠 System prompt — методика живой распаковки (с JSON-протоколом)
# -------------------------
SYSTEM_PROMPT = (
    "Ты — AILVI Guide. Ведёшь ЖИВУЮ распаковку личности: каждый следующий вопрос рождается из ответа. "
    "Твоя задача — задавать ровно ОДИН короткий вопрос за раз, мягко и конкретно. "
    "Метод: анализируй тон, ясность, скрытый запрос; выбирай тип вопроса (уточнение, углубление, ценности, "
    "примеры, роли, среда, действие и т.п.). Не давай длинных лекций. Не отвечай вместо человека. "
    "Говори на русском, бережно и просто. "
    "Ты ведёшь по этапам (маякам), но можешь адаптивно двигаться вперёд/назад. "
    "ОТВЕЧАЙ ТОЛЬКО JSON БЕЗ ПРЕАМБУЛ: "
    "{"
    "\"next_prompt\": \"короткий вопрос\", "
    "\"milestone_index\": int, "
    "\"milestone_title\": \"название маяка\", "
    "\"state_note\": \"краткая служебная заметка о том, что мы выяснили\""
    "}. "
    "milestone_index — от 0 до 20 (соответствует списку маяков). "
    "Если ответ пользователя поверхностный или расплывчатый — сначала уточни. "
    "Если ответ зрелый — можешь предложить следующий под-шаг внутри того же маяка. "
    "Всегда держи фокус: один вопрос — один шаг. "
)

INTRO_TEXT = (
    "Ассаляму Алейкум. Я буду вести тебя шаг за шагом — мягко и без спешки. "
    "Пиши искренне и коротко. Начнём."
)

FINISH_HINT = (
    "Когда почувствуешь, что получил важные выводы, я помогу собрать их в один лист стратегии."
)

# -------------------------
# 🔎 helpers
# -------------------------
def get_engine_state(ctx: ContextTypes.DEFAULT_TYPE) -> dict:
    return ctx.user_data.get("engine", {"milestone_index": 0, "state_note": ""})

def set_engine_state(ctx: ContextTypes.DEFAULT_TYPE, state: dict):
    ctx.user_data["engine"] = state

def milestone_title(i: int) -> str:
    i = max(0, min(len(MILESTONES) - 1, i))
    return MILESTONES[i]

# -------------------------
# 🤖 Handlers
# -------------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Сбрасываем состояние и даём первый вопрос через двигатель
    set_engine_state(context, {"milestone_index": 0, "state_note": ""})
    await update.message.reply_text(INTRO_TEXT)

    # Просим первый шаг у модели: без пользовательского контекста — стартовое намерение
    seed_user = "Хочу начать распаковку. Помоги мне обозначить намерение и рамку."
    payload = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": json.dumps({
            "user_message": seed_user,
            "current_milestone_index": 0,
            "current_milestone_title": milestone_title(0),
            "state_note": ""
        }, ensure_ascii=False)}
    ]
    try:
        resp = client.chat.completions.create(model="gpt-4o-mini", messages=payload)
        raw = resp.choices[0].message.content if resp.choices else None
        data = json.loads(raw) if raw else {}
    except Exception as e:
        log.exception("start completion error:")
        data = {
            "next_prompt": "С чего хочешь начать? Одним предложением — твоё намерение.",
            "milestone_index": 0,
            "milestone_title": milestone_title(0),
            "state_note": "fallback"
        }

    set_engine_state(context, {
        "milestone_index": int(data.get("milestone_index", 0)),
        "state_note": str(data.get("state_note", ""))[:500]
    })
    # Заголовок маяка (не каждое сообщение, только при смене/старте — здесь уместно)
    await update.message.reply_text(f"🧭 Этап: {data.get('milestone_title', milestone_title(0))}")
    await update.message.reply_text(data.get("next_prompt", "Сформулируй своё намерение одним предложением."))

async def handle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return
    user_text = update.message.text.strip()
    eng = get_engine_state(context)
    idx = int(eng.get("milestone_index", 0))
    note = eng.get("state_note", "")

    # Формируем запрос к модели: прошлое состояние + новый ответ пользователя
    user_payload = {
        "user_message": user_text,
        "current_milestone_index": idx,
        "current_milestone_title": milestone_title(idx),
        "state_note": note
    }

    try:
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)}
            ],
            temperature=0.4,
            max_tokens=500
        )
        raw = resp.choices[0].message.content if resp.choices else None
        data = json.loads(raw) if raw else {}
    except Exception as e:
        log.exception("handle completion error:")
        data = {
            "next_prompt": "Понял. Скажи чуть конкретнее, что ты чувствуешь прямо сейчас?",
            "milestone_index": idx,
            "milestone_title": milestone_title(idx),
            "state_note": note
        }

    # Обновляем состояние
    new_idx = int(data.get("milestone_index", idx))
    new_note = str(data.get("state_note", note))[:600]
    title = data.get("milestone_title", milestone_title(new_idx))
    set_engine_state(context, {"milestone_index": new_idx, "state_note": new_note})

    # Если произошёл переход на новый маяк — мягко показать
    if new_idx != idx:
        await update.message.reply_text(f"🧭 Этап: {title}")

    # Один короткий следующий шаг
    nxt = data.get("next_prompt") or "Продолжим. Одной фразой — что самое главное в твоём ответе?"
    await update.message.reply_text(nxt)

# -------------------------
# 🚀 Runner
# -------------------------
def run_telegram():
    app = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle))
    log.info("✅ Telegram polling started")
    app.run_polling()

# -------------------------
# ✅ Main
# -------------------------
if __name__ == "__main__":
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()
    try:
        run_telegram()
    except Exception as e:
        log.exception("startup error:")
