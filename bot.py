# bot.py
import os
import threading
from collections import defaultdict
from flask import Flask
from telegram.ext import ApplicationBuilder, MessageHandler, CommandHandler, filters
from telegram import Update
from telegram.ext import ContextTypes
from openai import OpenAI

# ====== ENV ======
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
client = OpenAI(api_key=OPENAI_API_KEY)

# ====== Flask healthcheck ======
app = Flask(__name__)
@app.get("/")
def home():
    return "AILVI bot is alive"
def run_flask():
    app.run(host="0.0.0.0", port=10000)

# ====== In-memory sessions (простое состояние на тест) ======
# sessions[chat_id] = {
#   "started": bool,
#   "day": "day1",
#   "step": "intent_1" | "intent_2" | "alive_episodes_1" | "alive_episodes_2" | "summary_1",
#   "trace": [ {"q": "...", "a": "..."} ],
# }
sessions = defaultdict(dict)

# Небольшая карта прогресса на День 1 (достаточно для прогона; расширим позже)
FLOW = {
    "day1": ["intent_1", "intent_2", "alive_episodes_1", "alive_episodes_2", "summary_1"]
}

def _next_step(day: str, current: str) -> str | None:
    steps = FLOW.get(day, [])
    if current not in steps:
        return steps[0] if steps else None
    idx = steps.index(current)
    return steps[idx+1] if idx + 1 < len(steps) else None

# ====== GPT helper ======
SYSTEM_BASE = (
    "Ты — мягкий и точный проводник AILVI. Ведёшь человека по глубокой распаковке личности. "
    "Говоришь коротко, тепло и конкретно. Ни приветствий, ни «как дела». "
    "Всегда задавай ровно ОДИН фокус-вопрос, максимум 1–2 предложения. "
    "Не давай мини-лекций. Никакой болтовни. Вопрос рождай из последнего ответа пользователя."
)

def gpt_question(module_hint: str, history: list[dict], user_answer: str | None) -> str:
    """
    Возвращает один следующий вопрос. history — список {'q','a'}.
    module_hint определяет смысловой блок (шаг).
    """
    # Сжимаем историю в компактный контекст
    brief = []
    for turn in history[-6:]:  # последних 6 пар достаточно
        brief.append(f"Q: {turn['q']}\nA: {turn['a']}")
    brief_text = "\n".join(brief) if brief else "пока ответов нет"

    module_instruction = {
        "intent_1": "Модуль: День 1 — Намерение и рамка. Задай вопрос, который проясняет зачем человеку распаковка и какое решение он хочет принять.",
        "intent_2": "Уточни цель: какая польза/изменение ожидается для себя и других? Спросить конкретнее.",
        "alive_episodes_1": "Переход к «дням, когда я живой». Попроси описать 1 свежий эпизод: контекст, что делал, с кем, почему чувствовалась энергия.",
        "alive_episodes_2": "Попроси второй эпизод по той же форме, чтобы увидеть повторяющиеся мотивы.",
        "summary_1": "Попроси коротко назвать 2–3 наблюдения, что повторяется в эпизодах (мотивы, условия, роли). Один вопрос."
    }.get(module_hint, "Задай один уместный следующий вопрос по распаковке.")

    messages = [
        {"role": "system", "content": SYSTEM_BASE},
        {"role": "system", "content": module_instruction},
        {"role": "system", "content": f"Краткая история диалога:\n{brief_text}"},
    ]
    if user_answer:
        messages.append({"role": "user", "content": user_answer})

    resp = client.chat.completions.create(
        model="gpt-4o-mini",
        temperature=0.3,
        messages=messages,
    )
    return resp.choices[0].message.content.strip()

# ====== Telegram handlers ======
WELCOME = (
    "Ассаляму Алейкум. Запускаю распаковку.\n"
    "День 1 — *Намерение и рамка*.\n"
    "Отвечай свободно, коротко и по-делу — я буду вести шаг за шагом."
)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    s = sessions[chat_id]
    s.clear()
    s["started"] = True
    s["day"] = "day1"
    s["step"] = "intent_1"
    s["trace"] = []
    # Сразу первый вопрос без «как дела»
    q = gpt_question("intent_1", s["trace"], user_answer=None)
    await update.message.reply_text(WELCOME, parse_mode="Markdown")
    await update.message.reply_text(q)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    text = update.message.text.strip()

    s = sessions[chat_id]
    # Если сессии нет — инициируем как при /start
    if not s.get("started"):
        s["started"] = True
        s["day"] = "day1"
        s["step"] = "intent_1"
        s["trace"] = []
        await update.message.reply_text(WELCOME, parse_mode="Markdown")
        q = gpt_question("intent_1", s["trace"], user_answer=None)
        await update.message.reply_text(q)
        return

    # Записываем последний ответ
    last_q = s["trace"][-1]["q"] if s["trace"] else "(первый вопрос)"
    s["trace"].append({"q": last_q, "a": text})

    # Генерируем следующий вопрос в рамках текущего шага
    step = s["step"]
    q = gpt_question(step, s["trace"], user_answer=text)
    await update.message.reply_text(q)

    # Решаем — оставаться в шаге или двигаться дальше
    # Простая логика: после intent_1 → intent_2; после intent_2 → alive_episodes_1; после alive_episodes_2 → summary_1
    # (при необходимости уточним пороги/условия)
    step_next = {
        "intent_1": "intent_2",
        "intent_2": "alive_episodes_1",
        "alive_episodes_1": "alive_episodes_2",
        "alive_episodes_2": "summary_1",
        "summary_1": None
    }.get(step)

    if step_next:
        s["step"] = step_next
    else:
        # Завершили День 1 — дадим мягкое завершение и предложим продолжить позже
        await update.message.reply_text(
            "Спасибо. У нас есть первичная рамка и наблюдения. Готов продолжить в следующий раз — перейдём к ценностям и картированию энергии."
        )

def run_telegram():
    application = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    print("✅ Telegram polling started")
    application.run_polling()

# ====== Main ======
if __name__ == "__main__":
    t = threading.Thread(target=run_flask, daemon=True)
    t.start()
    run_telegram()
