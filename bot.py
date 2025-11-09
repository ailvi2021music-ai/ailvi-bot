import os
import threading
from flask import Flask
from telegram.ext import ApplicationBuilder, MessageHandler, CommandHandler, filters, ContextTypes
from openai import OpenAI

# -------------------------
# 🔑 API keys
# -------------------------
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
client = OpenAI(api_key=OPENAI_API_KEY)

# -------------------------
# 📦 Капсулы (сжато в system-prompt)
# -------------------------
CAPSULE_SYSTEM = """
Ты — мягкий, созерцательный AILVI-наставник. Тон — тёплый, духовный, без нажима.
Исламские правила: без перефразов аятов/хадисов; уважительный язык. 
Курс «Глубокая распаковка личности» (21 шага): сбор фактов → гипотезы → микро-пробы → стратегия.
Диалог живой: каждый следующий шаг — из ответа человека. Никаких коуч-клише и ярлыков.
Пиши нейтрально по роду (без «готов/готова», избегай форм, требующих муж./жен. окончания).
Используй эмодзи умеренно: 0–2 уместных на сообщение (например ✨🤲🏻🧭🌿💭), не в каждую строку.
Стиль: короткие абзацы, доброжелательно, задавай один точный вопрос за раз.
Цель — помочь увидеть ценности, сильные стороны, естественные роли и ближайшие малые шаги служения.
"""

# -------------------------
# 🧭 Тексты
# -------------------------
WELCOME_TEXT = (
    "Ассаляму Алейкум уа РахматуЛлахи уа Баракятух! 👋🏻\n\n"
    "Добро пожаловать в пространство, где Сердце узнаёт себя заново.\n\n"
    "Давай вместе, спокойно, шаг за шагом откроем дары, которые Аллах уже вложил "
    "в твою душу — силы, таланты и намерения. 💎\n\n"
    "Пусть Аллах сделает этот путь лёгким, благословенным и наполненным пониманием!\n\n"
    "Чтобы начать глубокую распаковку — напиши: «Начинаем»"
)

DEEP_Q1 = (
    "С радостью. Начнём с самого важного для тебя сейчас. ✨\n\n"
    "Какое намерение хочется прояснить и какое решение ищется в жизни?\n"
    "Можно коротко: «понять свою естественную силу и как служить ею другим», «найти ясность в работе», и т.п. 💭"
)

# -------------------------
# 🛠 Простая сессия в памяти процесса
# -------------------------
SESSIONS = {}  # chat_id -> {"started": bool}

def set_started(chat_id: int, v: bool = True):
    SESSIONS.setdefault(chat_id, {})["started"] = v

def is_started(chat_id: int) -> bool:
    return SESSIONS.get(chat_id, {}).get("started", False)

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
# 🤖 Telegram logic
# -------------------------
async def start(update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    set_started(chat_id, False)
    await update.message.reply_text(WELCOME_TEXT)

async def handle_message(update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    text = (update.message.text or "").strip()

    # Старт распаковки
    if text.lower() in ["начинаем", "начнем", "начинаю"]:
        set_started(chat_id, True)
        await update.message.reply_text(DEEP_Q1)
        return

    # Живой диалог распаковки
    if is_started(chat_id):
        system = CAPSULE_SYSTEM
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": text}
            ],
            temperature=0.5,
        )
        answer = resp.choices[0].message.content
        await update.message.reply_text(answer)
        return

    # До старта
    await update.message.reply_text("Готов приступить, когда скажешь «Начинаем».")

def run_telegram():
    application = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    print("✅ Telegram polling started")
    application.run_polling()

# -------------------------
# ✅ Main
# -------------------------
if __name__ == "__main__":
    t = threading.Thread(target=run_flask, daemon=True)
    t.start()
    run_telegram()
