import os
import threading
import traceback
from flask import Flask
from telegram.ext import ApplicationBuilder, MessageHandler, CommandHandler, filters
from openai import OpenAI

# -------------------------
# 🔑 API-ключи из переменных окружения
# -------------------------
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

client = OpenAI(api_key=OPENAI_API_KEY)

# -------------------------
# 🫶 Память (per-user) в процессе
# -------------------------
user_state = {}       # {user_id: {"mode": "idle"|"deep", "step": int}}
conversations = {}    # {user_id: [{"role":"system|user|assistant","content":str}]}

# -------------------------
# 🧭 Системный промпт (концентрат капсул)
# -------------------------
SYSTEM_PROMPT = (
    "Ты — AILVI-проводник: мягкий, спокойный, доброжелательный. Роль: духовно-научная распаковка личности "
    "с упором на служение Аллаху. Говори коротко, тепло, без давления; используй тёплые связки "
    "«и знаешь…», «посмотри…», «иногда мы забываем…». Не выноси приговоров; никаких коуч-клише.\n\n"
    "Исламский вектор: намерение ради довольства Аллаха; халяль/харам; скромность; польза. Не цитируй аяты "
    "без запроса и не искажай смыслы.\n\n"
    "Методика: сначала глубокая индивидуальная распаковка (до любых «дней»). Каждый следующий вопрос "
    "рождается из ответа человека. Опирайся на наблюдаемое поведение, реальные эпизоды живости/потока, мотивы, "
    "среду; применяй идеи VIA, Big Five, RIASEC, «поток», микро-эксперименты — но не перегружай терминами, "
    "если их не просят. Помогай увидеть сильные стороны, ценности, естественные роли, среду раскрытия, формат "
    "работы, гипотезы служения и маленькие шаги.\n\n"
    "Стратегия диалога: 1) проясни намерение и ожидаемое решение; 2) попроси 2–3 живых эпизода с энергией; "
    "3) выдели мотивы/условия; 4) предложи 1–2 гипотезы ролей и попроси отклик; 5) дай микро-шаг (≤60 минут) "
    "и одну простую метрику; 6) спроси об ощущениях после шага. Один вопрос за раз. Мягко направляй к искреннему "
    "обращению к Аллаху, но не отвечай вместо человека."
)

# -------------------------
# 👋 Приветствие и сигнал запуска
# -------------------------
WELCOME_TEXT = (
    "Ассаляму Алейкум уа РахматуЛлахи уа Баракятух! 👋🏻\n\n"
    "Добро пожаловать в пространство, где Сердце узнаёт себя заново.\n\n"
    "Давай вместе, спокойно, шаг за шагом откроем драгоценные дары, которые Аллах уже вложил "
    "в твою Душу — силы, таланты, намерения, которые ждут, когда ты увидишь их Свет. 💎\n\n"
    "Пусть Аллах сделает этот путь лёгким, благословенным и наполненным пониманием!\n\n"
    "Чтобы начать глубокую распаковку — напиши: «Начинаем»"
)

DEEP_INTRO_USER_CUE = (
    "Начни глубокую распаковку до любых «дней». Сформулируй первый мягкий вопрос по намерению "
    "и ожидаемому решению (1 вопрос, 1–2 строки, с примером формулировки ответа)."
)

# -------------------------
# ✅ Flask health-check (для Render)
# -------------------------
app = Flask(__name__)

@app.route("/")
def home():
    return "AILVI bot is alive"

def run_flask():
    app.run(host="0.0.0.0", port=10000)

# -------------------------
# 🤖 Вызовы модели
# -------------------------
def ai_reply(user_id: int, user_text: str) -> str:
    if user_id not in conversations:
        conversations[user_id] = [{"role": "system", "content": SYSTEM_PROMPT}]
    conversations[user_id].append({"role": "user", "content": user_text})

    msgs = [conversations[user_id][0]] + conversations[user_id][-16:]
    resp = client.chat.completions.create(
        model="gpt-4o-mini",
        temperature=0.6,
        max_tokens=400,
        messages=msgs,
    )
    answer = resp.choices[0].message.content
    conversations[user_id].append({"role": "assistant", "content": answer})
    return answer

def ai_first_probe(user_id: int) -> str:
    conversations[user_id] = [{"role": "system", "content": SYSTEM_PROMPT}]
    resp = client.chat.completions.create(
        model="gpt-4o-mini",
        temperature=0.6,
        max_tokens=300,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": DEEP_INTRO_USER_CUE},
        ],
    )
    answer = resp.choices[0].message.content
    conversations[user_id].append({"role": "assistant", "content": answer})
    return answer

# -------------------------
# 📲 Telegram handlers
# -------------------------
async def start(update, context):
    user_id = update.effective_user.id
    user_state[user_id] = {"mode": "idle", "step": 0}
    conversations.pop(user_id, None)
    await update.message.reply_text(WELCOME_TEXT)

async def handle_message(update, context):
    try:
        user_id = update.effective_user.id
        text = (update.message.text or "").strip()

        # Старт глубокой распаковки
        if text.lower() == "начинаем":
            user_state[user_id] = {"mode": "deep", "step": 1}
            first = ai_first_probe(user_id)
            await update.message.reply_text(first)
            return

        mode = user_state.get(user_id, {}).get("mode", "idle")
        if mode == "idle":
            await update.message.reply_text(
                "Напиши «Начинаем», и мы сразу перейдём к глубокой распаковке. "
                "Чтобы обновить приветствие — отправь /start."
            )
            return

        answer = ai_reply(user_id, text)
        await update.message.reply_text(answer)

    except Exception as e:
        print("Error in handle_message:", e, traceback.format_exc())
        await update.message.reply_text("Похоже, возникла техническая заминка. Попробуй ещё раз.")

def run_telegram():
    application = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    print("✅ Telegram polling started")
    application.run_polling()

# -------------------------
# 🚀 Main
# -------------------------
if __name__ == "__main__":
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()
    run_telegram()
